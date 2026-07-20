"""
死链异步巡检脚本

功能：
- 扫描 data_resources 表中所有 active 状态的图片记录
- 通过 MinIO stat_object() 检查文件是否存在
- 对于 file_path 指向外部 HTTP URL 的记录，使用 aiohttp HEAD 请求作为备用检查
- 超时阈值 5s
- 标记失效记录：data_resources.status = 'broken'
- 生成巡检报告（总扫描数 / 死链数 / 失效率 / 详细列表）

部署方式：
- Celery Beat 定时任务（后续）
- 或手动执行：python scripts/dead_link_checker.py

用法：
    cd backend
    python scripts/dead_link_checker.py [--mark-broken] [--dry-run]

选项：
    --mark-broken  标记失效记录为 broken（默认仅扫描不标记）
    --dry-run       试运行，不执行任何写入操作
    --batch-size N  每批处理数量（默认 100）
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from time import time
from typing import Any

import aiohttp

# 添加 backend 目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minio import Minio
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal


# ═══════════════════════════════════════════════════════════════════════════════
# MinIO 客户端
# ═══════════════════════════════════════════════════════════════════════════════

_minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def _parse_minio_path(file_path: str) -> tuple[str, str] | None:
    """解析 file_path 为 (bucket, object_name)。

    支持两种格式：
    - /detection-platform/images/abc.jpg → (detection-platform, images/abc.jpg)
    - http(s)://... → 返回 None（走 HTTP HEAD 备用检查）
    """
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return None

    path = file_path.lstrip("/")
    parts = path.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return settings.MINIO_BUCKET, path  # fallback


def check_minio_file(file_path: str) -> dict[str, Any]:
    """通过 MinIO stat_object 检查文件是否存在。

    返回 {exists: bool, error: str | None}
    """
    parsed = _parse_minio_path(file_path)
    if parsed is None:
        # 外部 URL，走 HTTP 检查
        return {"exists": "external", "error": None}

    bucket, object_name = parsed
    try:
        _minio_client.stat_object(bucket, object_name)
        return {"exists": True, "error": None}
    except Exception as e:
        return {"exists": False, "error": str(e)}


async def check_http_url(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """通过 HTTP HEAD 检查外部 URL 连通性。

    返回 {status_code: int, exists: bool, error: str | None}
    """
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            exists = 200 <= resp.status < 400
            return {"status_code": resp.status, "exists": exists, "error": None}
    except asyncio.TimeoutError:
        return {"status_code": 0, "exists": False, "error": "timeout (5s)"}
    except Exception as e:
        return {"status_code": 0, "exists": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 主巡检逻辑
# ═══════════════════════════════════════════════════════════════════════════════


def scan_resources(batch_size: int = 100) -> list[dict[str, Any]]:
    """分批查询所有 active 状态的 data_resources。

    返回 [{resource_id, name, file_path, modality}] 列表。
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT resource_id, name, file_path, modality "
                "FROM data_resources "
                "WHERE status = 'active' "
                "ORDER BY resource_id"
            )
        ).fetchall()

        return [
            {
                "resource_id": r[0],
                "name": r[1],
                "file_path": r[2],
                "modality": r[3],
            }
            for r in rows
        ]
    finally:
        db.close()


def mark_broken(resource_ids: list[int]) -> int:
    """标记 resources 为 broken 状态。

    返回实际更新的行数。
    """
    if not resource_ids:
        return 0

    db = SessionLocal()
    try:
        # 分批更新，避免一条 SQL 过长
        total_updated = 0
        chunk_size = 500
        for i in range(0, len(resource_ids), chunk_size):
            chunk = resource_ids[i : i + chunk_size]
            placeholders = ",".join([str(rid) for rid in chunk])
            result = db.execute(
                text(
                    f"UPDATE data_resources SET status = 'broken' "
                    f"WHERE resource_id IN ({placeholders}) "
                    f"AND status = 'active'"
                )
            )
            total_updated += result.rowcount
        db.commit()
        return total_updated
    finally:
        db.close()


async def run_check(
    resources: list[dict[str, Any]],
    mark_broken_flag: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """执行巡检。

    对每个 resource：
    1. 优先 MinIO stat_object
    2. 若是外部 URL，用 aiohttp HEAD 备用检查
    3. 收集死链列表

    返回巡检报告 dict。
    """
    dead_links: list[dict[str, Any]] = []
    external_urls: list[dict[str, Any]] = []
    total = len(resources)
    start_time = time()

    # 收集需要 HTTP 检查的外部 URL
    minio_dead = 0
    for res in resources:
        result = check_minio_file(res["file_path"])
        if result["exists"] is True:
            continue  # MinIO 中存在
        elif result["exists"] == "external":
            external_urls.append(res)
        else:
            dead_links.append({
                "resource_id": res["resource_id"],
                "name": res["name"],
                "file_path": res["file_path"],
                "modality": res["modality"],
                "method": "minio",
                "error": result.get("error", "unknown"),
            })
            minio_dead += 1

    # HTTP HEAD 检查外部 URL
    http_dead = 0
    if external_urls:
        async with aiohttp.ClientSession() as session:
            tasks = [
                check_http_url(session, res["file_path"]) for res in external_urls
            ]
            http_results = await asyncio.gather(*tasks)

            for res, result in zip(external_urls, http_results):
                if not result["exists"]:
                    dead_links.append({
                        "resource_id": res["resource_id"],
                        "name": res["name"],
                        "file_path": res["file_path"],
                        "modality": res["modality"],
                        "method": "http",
                        "status_code": result.get("status_code", 0),
                        "error": result.get("error", "unknown"),
                    })
                    http_dead += 1

    elapsed = time() - start_time
    dead_count = len(dead_links)
    alive_count = total - dead_count
    dead_rate = (dead_count / total * 100) if total > 0 else 0

    # 标记 broken
    updated_count = 0
    if dead_links and mark_broken_flag and not dry_run:
        broken_ids = [d["resource_id"] for d in dead_links]
        updated_count = mark_broken(broken_ids)

    return {
        "total": total,
        "alive": alive_count,
        "dead": dead_count,
        "minio_dead": minio_dead,
        "http_dead": http_dead,
        "dead_rate": round(dead_rate, 2),
        "updated_count": updated_count,
        "elapsed_seconds": round(elapsed, 2),
        "dead_links": dead_links,
        "checked_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════════════════════


def generate_report(report: dict[str, Any]) -> str:
    """生成 Markdown 格式的巡检报告。"""
    lines = [
        "# 死链巡检报告",
        "",
        f"**巡检时间**：{report['checked_at']}",
        f"**耗时**：{report['elapsed_seconds']}s",
        "",
        "## 汇总",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 总扫描数 | {report['total']} |",
        f"| 存活数 | {report['alive']} |",
        f"| 死链数 | {report['dead']} |",
        f"| 失效率 | {report['dead_rate']}% |",
        f"| MinIO 死链 | {report['minio_dead']} |",
        f"| HTTP 死链 | {report['http_dead']} |",
    ]

    if report["updated_count"] > 0:
        lines.append(f"| 已标记 broken | {report['updated_count']} |")

    lines.extend(["", "## 死链详情", ""])

    if not report["dead_links"]:
        lines.append("✅ 未发现死链。")
    else:
        lines.append(
            "| resource_id | 文件名 | 检查方式 | 状态码 | 错误信息 |"
        )
        lines.append(
            "|------------|--------|---------|--------|---------|"
        )
        for d in report["dead_links"]:
            sc = d.get("status_code", "-")
            err = (d.get("error") or "")[:80]
            lines.append(
                f"| {d['resource_id']} | {d['name'][:40]} | {d['method']} | {sc} | {err} |"
            )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="死链异步巡检脚本")
    parser.add_argument(
        "--mark-broken",
        action="store_true",
        help="标记失效记录为 broken 状态",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="试运行模式（默认），不写入数据库",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="关闭试运行，实际执行标记操作",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="每批处理的记录数（默认 100）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="报告输出路径（默认打印到 stdout）",
    )
    args = parser.parse_args()

    dry_run = not args.no_dry_run

    print(f"[{datetime.now().isoformat()}] 开始巡检...")
    print(f"  模式: {'试运行 (dry-run)' if dry_run else '正式运行'}")
    print(f"  标记 broken: {'是' if args.mark_broken else '否'}")

    # 1. 扫描资源列表
    resources = scan_resources(args.batch_size)
    print(f"  待扫描资源数: {len(resources)}")

    if not resources:
        print("  没有需要扫描的资源，退出。")
        return

    # 2. 执行巡检
    report = asyncio.run(
        run_check(resources, mark_broken_flag=args.mark_broken, dry_run=dry_run)
    )

    # 3. 生成报告
    report_md = generate_report(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"  报告已写入: {args.output}")
    else:
        print()
        print(report_md)

    print(f"\n[{datetime.now().isoformat()}] 巡检完成。")


if __name__ == "__main__":
    main()
