#!/usr/bin/env python3
"""Inspect or synchronize the configured remote LH dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config
from src.io.remote_storage import RemoteDatasetStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "pull", "push"))
    parser.add_argument("path", nargs="?", default="")
    parser.add_argument("--small-only", action="store_true")
    args = parser.parse_args()

    store = RemoteDatasetStore.from_app_config(load_config())
    if store is None:
        raise SystemExit("remote_storage.enabled is false")
    with store:
        if args.command == "status":
            print("SFTP connection OK")
            print("Remote root:", store.remote_root)
            print("Local cache:", store.cache_root)
            for name in store.test_connection():
                print(" -", name)
            return 0
        if args.command == "pull":
            include = None
            if args.small_only:
                allowed = {".json", ".csv", ".txt", ".yaml", ".yml"}
                include = lambda entry: Path(entry.path).suffix.lower() in allowed
            count, size = store.pull_tree(
                args.path,
                include=include,
                progress=lambda path: print("pull", path),
            )
            print(f"Downloaded {count} files, {size / 1024 / 1024:.1f} MiB")
            return 0
        local = store.local_path(args.path)
        if not local.is_file():
            raise SystemExit(f"local cached file not found: {local}")
        store.push_file(local, args.path)
        print("Uploaded", args.path)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
