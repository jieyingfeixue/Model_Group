"""生成最小假权重，便于没有真实模型时联调注册/训练。

用法（在 backend 目录或项目根均可）：
  python backend/scripts/make_dummy_weight.py
  → 输出到 demo_assets/dummy_weights/
"""

from __future__ import annotations

import json
from pathlib import Path

# 写在 backend/demo_assets：Docker 挂载 ./backend:/app，重建容器不丢
BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "demo_assets" / "dummy_weights"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dummy.pt").write_bytes(b"DEMO_PYTORCH_WEIGHT_V1")
    (OUT / "dummy.pth").write_bytes(b"DEMO_PYTORCH_WEIGHT_V1")
    (OUT / "dummy.onnx").write_bytes(b"DEMO_ONNX_WEIGHT_V1")
    meta = {
        "note": "placeholder weights for Phase2 API tests",
        "files": ["dummy.pt", "dummy.pth", "dummy.onnx"],
    }
    (OUT / "README.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote dummy weights under {OUT}")


if __name__ == "__main__":
    main()
