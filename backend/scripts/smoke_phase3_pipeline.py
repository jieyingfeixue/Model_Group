"""Phase3 管道冒烟 — 不依赖真 YOLO / Celery。

步骤：
  1. MetricsEngine 单元路径（内存）
  2. 从 DB 加载夹具 GT（需先 seed_phase3_fixture.py）
  3. 合成推理结果 → build_eval_inputs → evaluate_detection
  4. 可选 --full：调用 run_eval_pipeline（占位 ONNX 会失败，仅在有真权重时试）

用法：
  cd backend
  python scripts/smoke_phase3_pipeline.py
  python scripts/smoke_phase3_pipeline.py --full
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 写在 backend/ 下：Docker 挂载 ./backend:/app，重建容器也不会丢
ASSETS = BACKEND / "demo_assets"
MANIFEST_PATH = ASSETS / "phase3_fixture" / "manifest.json"
# 兼容旧路径（曾写到容器根 /demo_assets，重建后会丢）
_LEGACY_MANIFEST = Path("/demo_assets/phase3_fixture/manifest.json")

PASS = 0
FAIL = 0


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")


def step_metrics_engine() -> None:
    from app.eval_engine.metrics_engine import ImageEvalInput, evaluate_detection

    images = [
        ImageEvalInput(
            image_id=1,
            width=100,
            height=100,
            gt_boxes=[{"category_id": 1, "x1": 10, "y1": 10, "x2": 50, "y2": 50}],
            pred_boxes=[],
        )
    ]
    out = evaluate_detection(images, category_names={1: "pole"})
    assert out["overall_metrics"]["mAP50"] == 0.0
    assert len(out["error_samples"]["fn"]) == 1


def _load_manifest() -> dict:
    candidates = [
        MANIFEST_PATH,
        _LEGACY_MANIFEST,
        BACKEND.parent / "demo_assets" / "phase3_fixture" / "manifest.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"未找到 manifest.json（已试: {[str(p) for p in candidates]}）。"
        "请先运行: python scripts/seed_phase3_fixture.py"
        "（若夹具已在库中只需重建 manifest，加 --force）"
    )

def step_gt_from_db(manifest: dict) -> dict[int, list]:
    from app.core.database import SessionLocal
    from app.services.eval_runtime import load_gt_for_images

    resource_ids = [r["resource_id"] for r in manifest["resources"]]
    db = SessionLocal()
    try:
        gt_map = load_gt_for_images(db, resource_ids)
        assert sum(1 for v in gt_map.values() if v) >= 2, "GT 条数过少"
        return gt_map
    finally:
        db.close()


def step_synthetic_eval(manifest: dict, gt_map: dict[int, list]) -> None:
    from app.eval_engine.metrics_engine import evaluate_detection
    from app.services.eval_runtime import build_eval_inputs

    detections = []
    for res in manifest["resources"]:
        rid = res["resource_id"]
        gts = gt_map.get(rid) or []
        if not gts:
            continue
        gt = gts[0]
        w = int(gt.get("image_width") or 320)
        h = int(gt.get("image_height") or 240)
        # 与 GT 同框的高置信预测 → mAP 应 > 0
        detections.append(
            {
                "image_id": rid,
                "image_width": w,
                "image_height": h,
                "boxes": [
                    {
                        "category_id": gt["category_id"],
                        "confidence": 0.95,
                        "xyxy_pixel": [gt["x1"], gt["y1"], gt["x2"], gt["y2"]],
                    }
                ],
            }
        )

    infer_results = {"detections": detections, "total_images": len(detections)}
    inputs = build_eval_inputs(infer_results, gt_map)
    cats = {i + 1: name for i, name in enumerate(manifest["model"]["categories"])}
    metrics = evaluate_detection(inputs, category_names=cats)
    assert metrics["overall_metrics"]["mAP50"] > 0, "合成评测 mAP50 应为正"
    assert "engine" in metrics["overall_metrics"]


def step_full_pipeline(manifest: dict) -> None:
    from app.core.database import SessionLocal
    from app.services.eval_runtime import run_eval_pipeline

    db = SessionLocal()
    try:
        run_eval_pipeline(
            db,
            model_id=manifest["model"]["model_id"],
            dataset_id=manifest["dataset"]["dataset_id"],
            metric_config={"conf_thres": 0.25},
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        action="store_true",
        help="尝试整集 ONNX 推理（需真权重；占位 ONNX 预期失败）",
    )
    args = parser.parse_args()

    print("Phase3 smoke pipeline")
    print("=" * 50)

    check("MetricsEngine 空预测容错", step_metrics_engine)

    manifest = _load_manifest()
    print(f"  manifest: dataset_id={manifest['dataset']['dataset_id']}, "
          f"model_id={manifest['model']['model_id']}")

    gt_map: dict[int, list] = {}

    def _gt():
        nonlocal gt_map
        gt_map = step_gt_from_db(manifest)

    check("DB 加载夹具 GT", _gt)
    check("合成推理 + 真指标", lambda: step_synthetic_eval(manifest, gt_map))

    if args.full:
        def _full():
            step_full_pipeline(manifest)

        check("run_eval_pipeline（真 ONNX，占位权重可能 FAIL）", _full)

    print("=" * 50)
    print(f"结果: {PASS} pass, {FAIL} fail")
    if FAIL:
        sys.exit(1)
    print("smoke_phase3_ok")


if __name__ == "__main__":
    main()
