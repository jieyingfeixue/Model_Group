#!/usr/bin/env python3
"""Incrementally upload LH annotation directories to the configured NAS."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config
from src.io.remote_storage import RemoteDatasetStore


DEFAULT_UPLOADS = (
    (
        Path(r"L:\LH_data_all_sensor_annotations"),
        "LH_data_all_sensor_annotations",
    ),
    (
        Path(r"L:\LH_data_all_sensor_annotations_autofill"),
        "LH_data_all_sensor_annotations_autofill",
    ),
)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GiB"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upload manual and autofill LabelMe annotations to "
            "/homes/LH_Dataset using SFTP."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compare files and print what would be uploaded.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count per failed file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print skipped files as well as uploaded files.",
    )
    args = parser.parse_args()

    missing = [str(local) for local, _remote in DEFAULT_UPLOADS if not local.is_dir()]
    if missing:
        raise SystemExit("Local annotation directories not found: " + ", ".join(missing))

    store = RemoteDatasetStore.from_app_config(load_config())
    if store is None:
        raise SystemExit("remote_storage.enabled is false")

    total_uploaded = total_skipped = total_failed = total_bytes = 0
    started = time.monotonic()

    def progress(action: str, path: str, size: int) -> None:
        if action == "skip" and not args.verbose:
            return
        print(f"[{action:12}] {_format_size(size):>10}  {path}", flush=True)

    with store:
        roots = store.test_connection()
        print(
            f"Connected to {store.host}:{store.port}{store.remote_root}",
            flush=True,
        )
        print("Remote directories:", ", ".join(roots), flush=True)
        for local_root, remote_name in DEFAULT_UPLOADS:
            print(
                f"\n{local_root} -> {store.remote_root}/{remote_name}",
                flush=True,
            )
            result = store.push_tree(
                local_root,
                remote_name,
                dry_run=args.dry_run,
                retries=max(1, args.retries),
                progress=progress,
            )
            total_uploaded += result.uploaded_files
            total_skipped += result.skipped_files
            total_failed += result.failed_files
            total_bytes += result.uploaded_bytes
            print(
                "Result: "
                f"uploaded={result.uploaded_files}, "
                f"skipped={result.skipped_files}, "
                f"failed={result.failed_files}, "
                f"bytes={_format_size(result.uploaded_bytes)}",
                flush=True,
            )

    elapsed = time.monotonic() - started
    mode = "DRY RUN" if args.dry_run else "UPLOAD"
    print(
        f"\n{mode} complete in {elapsed:.1f}s: "
        f"uploaded={total_uploaded}, skipped={total_skipped}, "
        f"failed={total_failed}, bytes={_format_size(total_bytes)}"
    )
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
