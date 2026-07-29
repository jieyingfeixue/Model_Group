"""Vision Agent — Qwen2.5-VL-72B for image-level review."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import cv2
import numpy as np

from src.core.types import CalibrationBundle, Label3D, VisionVerification

logger = logging.getLogger(__name__)


class VisionAgent:
    """Uses Qwen2.5-VL (local vLLM or API) for visual annotation verification."""

    def __init__(self, config: dict[str, Any]):
        self.enabled = config.get("enabled", False)
        self.model = config.get("model", "qwen2.5-vl-72b-instruct")
        self._provider = config.get("provider", "local")
        self._endpoint = config.get("endpoint", "http://localhost:8000/v1")
        self._client = None

    def _ensure_client(self):
        if self._client is not None or not self.enabled:
            return
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self._endpoint,
                api_key="EMPTY",
            )
        except ImportError:
            logger.error("openai package not installed for vision agent")
            raise

    async def verify_boxes_on_image(
        self,
        image: np.ndarray,
        boxes: list[Label3D],
        calib: CalibrationBundle | None,
        camera: str,
    ) -> list[VisionVerification]:
        """Project boxes onto image and ask VL model to verify."""
        if not self.enabled or not boxes:
            return []

        self._ensure_client()
        if self._client is None:
            return []

        annotated = _render_projected_boxes(image, boxes, calib, camera)
        img_b64 = _encode_base64(annotated)

        prompt = """请审查这张标注图像。图中的彩色方框是 3D 标注框在图像上的投影。

请检查:
1. 每个框是否对准了对应的目标物体？
2. 框的类别标签是否正确？
3. 图像中是否有明显的未标注目标？

以 JSON 格式回答:
{
  "box_reviews": [
    {"box_id": "...", "alignment": "good", "class_correct": true, "suggested_class": "", "notes": ""}
  ]
}"""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=2048,
                temperature=0.1,
            )
            text = response.choices[0].message.content or ""
            return _parse_vision_result(text, boxes)
        except Exception as exc:
            logger.error("Vision agent call failed: %s", exc)
            return []


def _render_projected_boxes(
    image: np.ndarray,
    boxes: list[Label3D],
    calib: CalibrationBundle | None,
    camera: str,
) -> np.ndarray:
    """Draw projected 3D box wireframes on the image."""
    vis = image.copy()
    colors = [
        (0, 255, 0), (255, 128, 0), (0, 128, 255),
        (255, 255, 0), (255, 0, 0), (128, 0, 255),
    ]
    for i, box in enumerate(boxes):
        color = colors[i % len(colors)]
        if calib is not None and camera in calib.intrinsics:
            try:
                corners = box.corners()
                pts_2d = calib.project_3d_to_image(corners, camera)
                pts_2d = pts_2d.astype(int)
                # Draw bottom and top faces
                for face in [[0, 1, 2, 3], [4, 5, 6, 7]]:
                    for j in range(4):
                        p1 = tuple(pts_2d[face[j]])
                        p2 = tuple(pts_2d[face[(j + 1) % 4]])
                        cv2.line(vis, p1, p2, color, 2)
                # Pillars
                for j in range(4):
                    cv2.line(vis, tuple(pts_2d[j]), tuple(pts_2d[j + 4]), color, 1)
                # Label
                cx = int(pts_2d[:, 0].mean())
                cy = int(pts_2d[:, 1].min()) - 5
                cv2.putText(vis, f"{box.object_id}:{box.class_name}", (cx, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            except Exception:
                pass
    return vis


def _encode_base64(image: np.ndarray) -> str:
    _, buf = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _parse_vision_result(text: str, boxes: list[Label3D]) -> list[VisionVerification]:
    results = []
    try:
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            for r in data.get("box_reviews", []):
                results.append(VisionVerification(
                    box_id=r.get("box_id", ""),
                    alignment=r.get("alignment", "good"),
                    class_correct=r.get("class_correct", True),
                    suggested_class=r.get("suggested_class", ""),
                    notes=r.get("notes", ""),
                ))
    except (json.JSONDecodeError, KeyError):
        logger.debug("Failed to parse vision result: %s", text[:200])
    return results
