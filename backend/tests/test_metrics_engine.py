"""MetricsEngine 单元测试 — 不依赖真模型 / DB。"""

from app.eval_engine.metrics_engine import ImageEvalInput, evaluate_detection


def test_empty_predictions_with_gt():
    images = [
        ImageEvalInput(
            image_id=1,
            width=100,
            height=100,
            gt_boxes=[{"category_id": 1, "x1": 10, "y1": 10, "x2": 50, "y2": 50}],
            pred_boxes=[],
        )
    ]
    out = evaluate_detection(images, category_names={1: "a"})
    assert out["overall_metrics"]["mAP50"] == 0.0
    assert len(out["error_samples"]["fn"]) == 1
    assert out["error_samples"]["fp"] == []


def test_perfect_match():
    images = [
        ImageEvalInput(
            image_id=1,
            width=100,
            height=100,
            gt_boxes=[{"category_id": 1, "x1": 10, "y1": 10, "x2": 50, "y2": 50}],
            pred_boxes=[
                {
                    "category_id": 1,
                    "confidence": 0.99,
                    "x1": 10,
                    "y1": 10,
                    "x2": 50,
                    "y2": 50,
                }
            ],
        )
    ]
    out = evaluate_detection(images, category_names={1: "a"})
    assert out["overall_metrics"]["mAP50"] >= 0.99
    assert out["overall_metrics"]["precision"] >= 0.99
    assert len(out["error_samples"]["tp"]) == 1


def test_no_gt_no_pred():
    images = [
        ImageEvalInput(
            image_id=1, width=100, height=100, gt_boxes=[], pred_boxes=[]
        )
    ]
    out = evaluate_detection(images)
    assert "mAP50" in out["overall_metrics"]
    assert out["error_samples"]["fp"] == []
    assert out["error_samples"]["fn"] == []


if __name__ == "__main__":
    test_empty_predictions_with_gt()
    test_perfect_match()
    test_no_gt_no_pred()
    print("metrics_tests_ok")
