# -*- coding: utf-8 -*-
"""清理指定采集会话在库中的导入记录（重导前使用）。

默认只删 data_resources；若存在 dataset_items / alignment_groups 会一并清理关联行。
不删 MinIO 对象（可随后由导入覆盖同名路径）。

用法:
  python scripts/cleanup_capture_imports.py --dry-run
  python scripts/cleanup_capture_imports.py --yes
  python scripts/cleanup_capture_imports.py --yes --batch with_cameras_capture_20260427_151113
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

DB_URL = "postgresql://postgres:123456@localhost:5432/detection_platform"

DEFAULT_BATCHES = [
    "with_cameras_capture_20260430_202854",
]


def table_exists(db, name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :t
            """
        ),
        {"t": name},
    ).fetchone()
    return row is not None


def main() -> None:
    p = argparse.ArgumentParser(description="清理采集会话导入数据")
    p.add_argument("--db", default=DB_URL)
    p.add_argument("--batch", action="append", dest="batches", help="可多次指定 batch_id")
    p.add_argument("--dry-run", action="store_true", help="只统计不删除")
    p.add_argument("--yes", action="store_true", help="确认执行删除")
    args = p.parse_args()

    batches = args.batches or DEFAULT_BATCHES
    engine = create_engine(args.db)

    with engine.begin() as db:
        print("将清理的 batch_id:")
        for b in batches:
            n = db.execute(
                text("SELECT COUNT(*) FROM data_resources WHERE metadata->>'batch_id' = :b"),
                {"b": b},
            ).scalar()
            print(f"  {b}: {n} 条 data_resources")

        # 无 batch_id 的残留（早期测试）
        null_n = db.execute(
            text(
                """
                SELECT COUNT(*) FROM data_resources
                WHERE metadata->>'batch_id' IS NULL
                   OR NOT (metadata ? 'batch_id')
                """
            )
        ).scalar()
        print(f"  (无 batch_id): {null_n} 条")

        if args.dry_run:
            print("dry-run 结束，未删除")
            return
        if not args.yes:
            print("未加 --yes，拒绝删除。确认后请加 --yes，或先 --dry-run 查看。")
            sys.exit(1)

        ids = db.execute(
            text(
                """
                SELECT resource_id FROM data_resources
                WHERE metadata->>'batch_id' = ANY(:batches)
                   OR metadata->>'batch_id' IS NULL
                   OR NOT (metadata ? 'batch_id')
                """
            ),
            {"batches": batches},
        ).fetchall()
        resource_ids = [int(r[0]) for r in ids]
        print(f"待删 resource_id 数: {len(resource_ids)}")
        if not resource_ids:
            print("无需删除")
            return

        if table_exists(db, "dataset_items"):
            r = db.execute(
                text("DELETE FROM dataset_items WHERE resource_id = ANY(:ids)"),
                {"ids": resource_ids},
            )
            print(f"  deleted dataset_items: {r.rowcount}")

        if table_exists(db, "alignment_group_members"):
            r = db.execute(
                text("DELETE FROM alignment_group_members WHERE resource_id = ANY(:ids)"),
                {"ids": resource_ids},
            )
            print(f"  deleted alignment_group_members: {r.rowcount}")
        elif table_exists(db, "alignment_groups"):
            # 有的库只按 metadata 挂资源，尽量按 batch 清
            try:
                r = db.execute(
                    text(
                        """
                        DELETE FROM alignment_groups
                        WHERE metadata->>'batch_id' = ANY(:batches)
                        """
                    ),
                    {"batches": batches},
                )
                print(f"  deleted alignment_groups: {r.rowcount}")
            except Exception as exc:
                print(f"  skip alignment_groups: {exc}")

        r = db.execute(
            text(
                """
                DELETE FROM data_resources
                WHERE resource_id = ANY(:ids)
                """
            ),
            {"ids": resource_ids},
        )
        print(f"  deleted data_resources: {r.rowcount}")
        print("完成。可以重新导入了。")


if __name__ == "__main__":
    main()
