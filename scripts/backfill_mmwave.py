# -*- coding: utf-8 -*-
"""为已导入的夜间会话补录毫米波资源（不重导全部数据）。

对齐策略与 import_segment_data 一致：
  - 文件名 FZxxxxx-yyyyy 按毫秒 → 会话时间
  - 帧在区间内均匀插值
  - 用 part 墙钟相对最早 part 的偏移 + 红外 t 对齐

用法:
  python scripts/backfill_mmwave.py --dry-run
  python scripts/backfill_mmwave.py --yes
  python scripts/backfill_mmwave.py --yes --batch with_cameras_capture_20260430_202854
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from bisect import bisect_left
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from minio import Minio
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent
MMWAVE_NAME = "mmwave_udp_radar"
BUCKET = "detection-platform"
MINIO = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:123456@localhost:5432/detection_platform"
)
DEFAULT_BATCH = "with_cameras_capture_20260430_202854"


def win_long_path(p: Path | str) -> str:
    s = str(p)
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + os.path.abspath(s)
    return s


def nearest_index(timestamps: list[float], target: float) -> int:
    if not timestamps:
        return -1
    idx = bisect_left(timestamps, target)
    if idx == 0:
        return 0
    if idx == len(timestamps):
        return len(timestamps) - 1
    left = timestamps[idx - 1]
    right = timestamps[idx]
    return idx - 1 if (target - left) <= (right - target) else idx


def parse_part_wall_ts(part_name: str) -> float | None:
    m = re.search(r"_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})$", part_name)
    if not m:
        return None
    y, mo, d, h, mi, s = map(int, m.groups())
    return datetime(y, mo, d, h, mi, s).timestamp()


def part_session_offsets(part_names: list[str]) -> dict[str, float]:
    walls = {p: parse_part_wall_ts(p) for p in part_names}
    valid = {p: t for p, t in walls.items() if t is not None}
    if not valid:
        return {p: 0.0 for p in part_names}
    t0 = min(valid.values())
    return {p: (valid[p] - t0) if p in valid else 0.0 for p in part_names}


def discover_mmwave_frames(capture_dir: Path) -> list[tuple[Path, int, float, str]]:
    out: list[tuple[Path, int, float, str]] = []
    mm_dirs = [
        p
        for p in capture_dir.iterdir()
        if p.is_dir() and "mmwave" in p.name.lower() and not p.name.startswith("@")
    ]
    for mm_dir in sorted(mm_dirs, key=lambda p: p.name):
        for mat_path in sorted(mm_dir.glob("*.mat")):
            m = re.search(r"FZ(\d+)-(\d+)", mat_path.name, re.IGNORECASE)
            if not m:
                continue
            fz_a, fz_b = int(m.group(1)), int(m.group(2))
            try:
                import scipy.io as sio

                data = sio.loadmat(win_long_path(mat_path), simplify_cells=True)
                n = len(data.get("Data_Ori", []))
            except Exception as exc:
                print(f"  [WARN] 读 mat 失败 {mat_path.name}: {exc}")
                continue
            if n <= 0:
                continue
            for i in range(n):
                fz = fz_a + (fz_b - fz_a) * ((i + 0.5) / n)
                out.append((mat_path, i, fz / 1000.0, f"{mat_path.name}::frame{i}"))
    out.sort(key=lambda x: x[2])
    return out


def upload_to_minio(fpath: Path, object_name: str) -> str:
    content_type = "application/octet-stream"
    if not MINIO.bucket_exists(BUCKET):
        MINIO.make_bucket(BUCKET)
    MINIO.fput_object(BUCKET, object_name, win_long_path(fpath), content_type=content_type)
    return f"/{BUCKET}/{object_name}"


def main() -> None:
    p = argparse.ArgumentParser(description="补录毫米波到已有样本组")
    p.add_argument("--db", default=DB_URL)
    p.add_argument("--batch", default=DEFAULT_BATCH)
    p.add_argument(
        "--capture",
        default=None,
        help="采集根目录（默认 BASE_DIR/<batch>）",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--max-diff", type=float, default=2.0, help="对齐最大时间差（秒）")
    args = p.parse_args()

    capture_dir = Path(args.capture) if args.capture else BASE_DIR / args.batch
    if not capture_dir.is_dir():
        raise SystemExit(f"找不到采集目录: {capture_dir}")

    print(f"batch={args.batch}")
    print(f"capture={capture_dir}")
    print("扫描 mmwave MAT …")
    mmwave_frames = discover_mmwave_frames(capture_dir)
    if not mmwave_frames:
        raise SystemExit("未发现 mmwave .mat")
    mm_ts = [t for _, _, t, _ in mmwave_frames]
    print(f"  帧数={len(mmwave_frames)}  时间={mm_ts[0]:.3f}~{mm_ts[-1]:.3f}s")

    engine = create_engine(args.db)
    with engine.begin() as db:
        existing = db.execute(
            text(
                """
                SELECT COUNT(*) FROM data_resources
                WHERE modality = 'mmwave'
                  AND metadata->>'batch_id' = :b
                """
            ),
            {"b": args.batch},
        ).scalar()
        print(f"  库中已有 mmwave: {existing}")

        ir_rows = db.execute(
            text(
                """
                SELECT resource_id, name, owner_id, metadata, captured_at
                FROM data_resources
                WHERE modality = 'infrared'
                  AND metadata->>'batch_id' = :b
                  AND metadata->>'sensor' = 'usb_ir__image_raw'
                ORDER BY (metadata->>'sample_group')::int NULLS LAST, resource_id
                """
            ),
            {"b": args.batch},
        ).mappings().all()
        print(f"  红外基准帧: {len(ir_rows)}")

        # 已有 mmwave 的 sample_group 跳过
        done_groups = {
            int(r[0])
            for r in db.execute(
                text(
                    """
                    SELECT DISTINCT (metadata->>'sample_group')::int
                    FROM data_resources
                    WHERE modality = 'mmwave'
                      AND metadata->>'batch_id' = :b
                      AND metadata ? 'sample_group'
                    """
                ),
                {"b": args.batch},
            ).fetchall()
            if r[0] is not None
        }

        part_names = sorted(
            {
                str((r["metadata"] or {}).get("part") or "")
                for r in ir_rows
                if (r["metadata"] or {}).get("part")
            }
        )
        offsets = part_session_offsets(part_names)
        print(f"  part 偏移: { {k: round(v, 1) for k, v in offsets.items()} }")

        plan: list[tuple] = []
        for row in ir_rows:
            meta = dict(row["metadata"] or {})
            sg = meta.get("sample_group")
            if sg is None:
                continue
            sg = int(sg)
            if sg in done_groups:
                continue
            part = str(meta.get("part") or "")
            ir_ts = float(meta.get("timestamp_offset", row["captured_at"] or 0))
            session_ts = offsets.get(part, 0.0) + ir_ts
            idx = nearest_index(mm_ts, session_ts)
            if idx < 0:
                continue
            mat_path, frame_idx, mts, dname = mmwave_frames[idx]
            diff = abs(mts - session_ts)
            if diff > args.max_diff:
                continue
            plan.append((row, sg, mat_path, frame_idx, mts, dname, diff, meta))

        print(f"  将补录: {len(plan)} 条（跳过已有组 {len(done_groups)}）")
        if plan:
            diffs = [x[6] for x in plan]
            print(f"  时间差: mean={sum(diffs)/len(diffs):.3f}s  max={max(diffs):.3f}s")

        if args.dry_run:
            print("dry-run 结束")
            return
        if not args.yes:
            print("未加 --yes，拒绝写入。确认后请加 --yes。")
            sys.exit(1)

        uploaded_mats: set[str] = set()
        inserted = 0
        for row, sg, mat_path, frame_idx, mts, dname, diff, meta in plan:
            object_name = f"{args.batch}/mmwave/{mat_path.name}"
            if object_name not in uploaded_mats:
                upload_to_minio(mat_path, object_name)
                uploaded_mats.add(object_name)
            file_path = f"/{BUCKET}/{object_name}"

            new_meta = {
                "width": 0,
                "height": 0,
                "channels": 0,
                "file_size": f"{os.stat(win_long_path(mat_path)).st_size // 1024}KB",
                "device": "毫米波雷达",
                "sensor": MMWAVE_NAME,
                "part": meta.get("part"),
                "segment": meta.get("segment"),
                "timestamp_offset": mts,
                "sample_group": sg,
                "is_primary": False,
                "modality": "mmwave",
                "mmwave_frame_index": frame_idx,
                "batch_id": args.batch,
                "weather": meta.get("weather"),
                "time_of_day": meta.get("time_of_day"),
                "terrain": meta.get("terrain"),
                "obstacle": meta.get("obstacle"),
                "scene": meta.get("scene"),
            }
            # 去掉 None
            new_meta = {k: v for k, v in new_meta.items() if v is not None}

            rid = db.execute(
                text(
                    """
                    INSERT INTO data_resources
                      (name, owner_id, modality, file_path, metadata, captured_at, version,
                       created_at, updated_at)
                    VALUES
                      (:name, :owner_id, 'mmwave', :file_path, CAST(:metadata AS jsonb), :captured_at, 1,
                       NOW(), NOW())
                    RETURNING resource_id
                    """
                ),
                {
                    "name": mat_path.name,
                    "owner_id": row["owner_id"],
                    "file_path": file_path,
                    "metadata": json.dumps(new_meta, ensure_ascii=False),
                    "captured_at": mts,
                },
            ).scalar()
            inserted += 1
            if inserted % 200 == 0 or inserted == 1:
                print(f"  已写入 {inserted}/{len(plan)} (rid={rid}, group={sg}, Δt={diff:.3f})")

        print(f"完成: 插入 {inserted} 条 mmwave，上传 MAT {len(uploaded_mats)} 个")


if __name__ == "__main__":
    main()
