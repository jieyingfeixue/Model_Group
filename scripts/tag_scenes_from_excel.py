"""
根据合规 Excel，给已入库的 data_resources 补写场景标签（写入 metadata JSONB）。

用法:
  python scripts/tag_scenes_from_excel.py
  python scripts/tag_scenes_from_excel.py --excel docs/test/compliance_paths_with_counts_new.xlsx
  python scripts/tag_scenes_from_excel.py --dry-run

匹配规则（不改文件夹/文件名）:
  1. metadata.batch_id == Excel 会话名
  2. 或 file_path / name / metadata 文本中包含 with_cameras_capture_* 会话名
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, text

from scene_tag_utils import DEFAULT_EXCEL, load_excel_folder_tags, normalize_batch_id, resolve_tags

DB_URL = "postgresql://postgres:123456@localhost:5432/detection_platform"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="用 Excel 给 data_resources 补场景标签")
    p.add_argument("--excel", default=str(DEFAULT_EXCEL), help="合规场景 Excel 路径")
    p.add_argument("--db", default=DB_URL, help="PostgreSQL 连接串")
    p.add_argument("--dry-run", action="store_true", help="只统计不写库")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    folder_tags = load_excel_folder_tags(args.excel)
    print(f"Excel: {args.excel}")
    print(f"会话标签数: {len(folder_tags)}")

    engine = create_engine(args.db)
    updated = 0
    matched = 0
    skipped = 0

    with engine.begin() as db:
        rows = db.execute(
            text(
                """
                SELECT resource_id, name, file_path, metadata
                FROM data_resources
                ORDER BY resource_id
                """
            )
        ).fetchall()

        print(f"库中资源: {len(rows)}")

        for resource_id, name, file_path, metadata in rows:
            meta = dict(metadata or {})
            # sqlalchemy 可能返回 str
            if isinstance(metadata, str):
                try:
                    meta = json.loads(metadata)
                except json.JSONDecodeError:
                    meta = {}

            batch_id = normalize_batch_id(str(meta.get("batch_id") or ""))
            if not batch_id:
                blob = "\\".join(
                    [
                        str(name or ""),
                        str(file_path or ""),
                        json.dumps(meta, ensure_ascii=False),
                    ]
                )
                batch_id = normalize_batch_id(blob)

            tags = resolve_tags(folder_tags, batch_id) if batch_id else None
            if not tags:
                skipped += 1
                continue

            matched += 1
            new_meta = {**meta, **tags}
            if "batch_id" not in new_meta and batch_id:
                new_meta["batch_id"] = batch_id
            if new_meta == meta:
                continue

            if args.dry_run:
                updated += 1
                if updated <= 5:
                    print(f"  [dry-run] #{resource_id} batch={batch_id} -> {tags.get('scene')}")
                continue

            db.execute(
                text(
                    """
                    UPDATE data_resources
                    SET metadata = CAST(:metadata AS jsonb),
                        updated_at = NOW()
                    WHERE resource_id = :rid
                    """
                ),
                {
                    "metadata": json.dumps(new_meta, ensure_ascii=False),
                    "rid": resource_id,
                },
            )
            updated += 1

    print("=" * 50)
    print(f"匹配到会话: {matched}")
    print(f"{'将更新' if args.dry_run else '已更新'}: {updated}")
    print(f"未匹配: {skipped}")
    if skipped and matched == 0:
        print(
            "提示: 若资源来自 segment_001 且路径不含 with_cameras_capture_*，"
            "请先在 metadata 写入 batch_id，或按云上会话目录重新导入。"
        )


if __name__ == "__main__":
    main()
