"""PyTorch → ONNX 尽力转换（Phase3 Step2）。

策略（按优先级）：
1. ultralytics.YOLO（若已安装）— 最适合 YOLOv8 .pt
2. torch.jit.load + torch.onnx.export — 适合 TorchScript
3. 否则给出可操作的失败原因（请装 ultralytics 或直接上传 .onnx）

torch / ultralytics 均为可选依赖，未安装时不阻塞纯 ONNX 推理。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_pt_bytes_to_onnx(
    pt_bytes: bytes,
    *,
    input_size: tuple[int, int] = (640, 640),
) -> bytes:
    """将 .pt/.pth 字节转为 ONNX 字节。失败抛 ValueError。"""
    if not pt_bytes or len(pt_bytes) < 32:
        raise ValueError("PyTorch 权重为空或过短")
    if pt_bytes.startswith(b"DEMO_PYTORCH") or pt_bytes.startswith(b"DEMO_ONNX"):
        raise ValueError("当前是联调占位权重，无法转换；请上传真实 .pt/.onnx")

    h, w = int(input_size[0]), int(input_size[1])
    if h < 32 or w < 32:
        h, w = 640, 640

    with tempfile.TemporaryDirectory(prefix="pt2onnx_") as tmp:
        tmp_path = Path(tmp)
        pt_path = tmp_path / "model.pt"
        onnx_path = tmp_path / "model.onnx"
        pt_path.write_bytes(pt_bytes)

        err_ultra = _try_ultralytics(pt_path, onnx_path, imgsz=max(h, w))
        if onnx_path.exists() and onnx_path.stat().st_size > 0:
            return onnx_path.read_bytes()

        err_torch = _try_torchscript_export(pt_path, onnx_path, h=h, w=w)
        if onnx_path.exists() and onnx_path.stat().st_size > 0:
            return onnx_path.read_bytes()

        raise ValueError(
            "PyTorch→ONNX 转换失败。"
            f" ultralytics: {err_ultra}; torch: {err_torch}."
            " 建议：pip install ultralytics（YOLO .pt）或直接上传 .onnx。"
        )


def _try_ultralytics(pt_path: Path, onnx_path: Path, imgsz: int) -> str:
    try:
        from ultralytics import YOLO
    except ImportError:
        return "未安装 ultralytics"

    try:
        model = YOLO(str(pt_path))
        exported = model.export(format="onnx", imgsz=imgsz, simplify=True)
        exported_path = Path(str(exported))
        if exported_path.exists():
            onnx_path.write_bytes(exported_path.read_bytes())
            return "ok"
        # 有的版本写到同目录 model.onnx
        sibling = pt_path.with_suffix(".onnx")
        if sibling.exists():
            onnx_path.write_bytes(sibling.read_bytes())
            return "ok"
        return "export 未生成文件"
    except Exception as exc:
        logger.exception("ultralytics export failed")
        return str(exc)


def _try_torchscript_export(pt_path: Path, onnx_path: Path, h: int, w: int) -> str:
    try:
        import torch
    except ImportError:
        return "未安装 torch"

    try:
        model = torch.jit.load(str(pt_path), map_location="cpu")
        model.eval()
        dummy = torch.zeros(1, 3, h, w)
        torch.onnx.export(
            model,
            dummy,
            str(onnx_path),
            input_names=["images"],
            output_names=["output"],
            opset_version=12,
            dynamic_axes={"images": {0: "batch"}, "output": {0: "batch"}},
        )
        return "ok"
    except Exception as exc:
        logger.exception("torchscript onnx export failed")
        # 再试 state_dict 类权重通常无法直接 export
        try:
            obj = torch.load(str(pt_path), map_location="cpu", weights_only=False)
            if isinstance(obj, dict):
                return (
                    "该 .pt 是 state_dict/检查点，需原模型结构才能导出；"
                    f"原始错误: {exc}"
                )
        except Exception:
            pass
        return str(exc)
