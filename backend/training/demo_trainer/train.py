"""Demo trainer — Phase2 验证训练链路用（CPU，无真实 GPU）。

约定 stdout 格式（Celery 解析）：
  PROGRESS epoch=<i> total_epochs=<n> loss=<f> map50=<f>
  DONE status=completed
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Detection platform demo trainer")
    parser.add_argument("--config", default="/workspace/config.json")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit(f"config not found: {cfg_path}")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    epochs = max(1, int(cfg.get("epochs", 5)))
    sleep_sec = float(cfg.get("sleep_sec", 1.0))
    output_path = Path(cfg.get("output_path", "/workspace/output/weights.pt"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seed_hint = cfg.get("model_id", 0)
    print(
        f"INFO demo trainer start model_id={seed_hint} epochs={epochs}",
        flush=True,
    )

    for epoch in range(1, epochs + 1):
        loss = round(1.0 / epoch + 0.05, 4)
        map50 = round(min(0.95, 0.12 * epoch), 4)
        print(
            f"PROGRESS epoch={epoch} total_epochs={epochs} loss={loss} map50={map50}",
            flush=True,
        )
        time.sleep(sleep_sec)

    # 伪权重：足够证明「产物回传 → 新版本」闭环
    payload = {
        "demo": True,
        "model_id": cfg.get("model_id"),
        "train_task_id": cfg.get("train_task_id"),
        "epochs": epochs,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"INFO wrote weights to {output_path}", flush=True)
    print("DONE status=completed", flush=True)


if __name__ == "__main__":
    main()
