"""VLM-based satellite-map region identification.

Given a camera photo (numpy RGB array) and a map screenshot (QPixmap or numpy
RGB array), asks a multimodal VLM to locate the corresponding
obstacles/structures visible in the camera image inside the satellite map, and
returns their bounding boxes in map-image pixel coordinates.

Supported providers (via ``vision_agent`` config block):
  * ``local``    – any OpenAI-compatible endpoint (e.g. vLLM serving Qwen2.5-VL)
  * ``openai``   – OpenAI GPT-4o / GPT-4.1 with vision
  * ``dashscope`` – Alibaba DashScope Qwen-VL API  (pip install dashscope)
  * ``anthropic`` – Anthropic Claude with vision   (pip install anthropic)

All provider calls are made through a two-step prompt:
  Step 1 – *describe*: ask the VLM to describe the main structures in the
           camera image and identify what it expects to see on the map.
  Step 2 – *locate*: ask it to find bounding boxes for those structures inside
           the satellite-map image (FOV region only) and return JSON.

A ``progress_cb(text: str)`` callable can be passed; it is called with partial
text chunks during streaming (step 1 description + step 2 boxes).
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "你是一个地理空间分析助手，擅长通过对比地面照片和卫星地图识别障碍物位置。"
)

_DESCRIBE_PROMPT = """\
图1是相机拍摄的地面照片。
请描述图1中你看到的主要障碍物（建筑物、铁塔、电杆、树木、构筑物等），
包括它们的外观特征、相对位置和大致规模。这将帮助在卫星地图上找到这些目标。
请用中文简洁回答（3-5句话即可）。
"""

_LOCATE_PROMPT = """\
图1是相机拍摄的地面照片。
图2是同一区域的卫星地图，图中蓝色虚线扇形是相机的视场角（FOV）范围，
图中 FOV 范围以外的雷达点已被隐藏，请只在蓝线围成的扇形区域内标注。

任务：根据图1中的障碍物，在图2的 FOV 范围内找出对应的区域并标矩形框。
要求：
- 只在蓝色虚线 FOV 扇形内标注
- 每个独立障碍物或紧凑的障碍物群各标一个矩形框
- 坐标以图2的像素为单位（左上角为原点）
- 直接输出 JSON，不要包含任何其他文字

输出格式：
[{"label": "建筑群", "x1": 120, "y1": 80, "x2": 340, "y2": 260}, ...]

若 FOV 范围内没有明显障碍物，输出空数组 []。
"""

# ── Image encoding helpers ────────────────────────────────────────────────────


def _ndarray_to_b64(img) -> str:
    """Encode numpy HxWx3 uint8 RGB array → base64 JPEG string."""
    import cv2
    import numpy as np
    arr = np.asarray(img, dtype=np.uint8)
    ok, buf = cv2.imencode(
        ".jpg",
        cv2.cvtColor(arr, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, 88],
    )
    if not ok:
        raise RuntimeError("cv2.imencode failed for camera image")
    return base64.b64encode(buf.tobytes()).decode()


# ── Main class ────────────────────────────────────────────────────────────────


class VLMMapQuery:
    """Query a multimodal VLM to locate obstacles in a satellite-map screenshot
    using a camera photo as a visual reference.

    Parameters
    ----------
    cfg : dict
        The ``vision_agent`` section from ``config/default.yaml``.
        Expected keys: ``provider``, ``model``, ``endpoint``,
        ``api_key_env`` (env-var name for the API key), ``fallback_provider``.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._provider = cfg.get("provider", "local")
        self._model    = cfg.get("model", "qwen2.5-vl-72b-instruct")
        self._endpoint = cfg.get("endpoint", "http://localhost:8000/v1")
        self._api_key  = (
            os.environ.get(cfg.get("api_key_env", "DASHSCOPE_API_KEY"), "") or ""
        )
        self._fallback = cfg.get("fallback_provider", "")

    # ── public ───────────────────────────────────────────────────────────────

    def query(
        self,
        cam_b64: str,
        map_b64: str,
        progress_cb: "Callable[[str], None] | None" = None,
    ) -> list[dict]:
        """Call VLM with camera + map images and return detected bboxes.

        Parameters
        ----------
        cam_b64 : base64-encoded JPEG of the camera frame
        map_b64 : base64-encoded JPEG of the map screenshot
        progress_cb : optional callable(text) called with streaming text chunks

        Returns a list of dicts with keys: label, x1, y1, x2, y2 (map pixels).
        Raises on error.
        """
        try:
            return self._dispatch(cam_b64, map_b64, self._provider, progress_cb)
        except Exception as primary_exc:
            # Skip fallback if no fallback configured or if it is the same
            fallback = self._fallback
            if not fallback or fallback == self._provider:
                raise
            # Try to import the fallback provider; if it is not installed,
            # re-raise the original error instead of hiding it.
            if fallback == "dashscope":
                try:
                    import dashscope  # noqa: F401
                except ImportError:
                    # dashscope 未安装时直接暴露主端点的原始错误
                    raise RuntimeError(
                        f"主端点 ({self._provider}) 调用失败：{primary_exc}\n"
                        f"（备用 dashscope 未安装，如需使用请 pip install dashscope）"
                    ) from primary_exc
            elif fallback == "anthropic":
                try:
                    import anthropic  # noqa: F401
                except ImportError:
                    raise RuntimeError(
                        f"主端点 ({self._provider}) 调用失败：{primary_exc}\n"
                        f"（备用 anthropic 未安装，如需使用请 pip install anthropic）"
                    ) from primary_exc
            logger.warning(
                "VLMMapQuery: primary provider %r failed (%s), trying fallback %r",
                self._provider, primary_exc, fallback,
            )
            if progress_cb:
                progress_cb(f"\n[主端点失败，尝试备用 {fallback}...]\n")
            return self._dispatch(cam_b64, map_b64, fallback, progress_cb)

    def describe(
        self,
        cam_b64: str,
        progress_cb: "Callable[[str], None] | None" = None,
        extra_context: str = "",
    ) -> str:
        """仅使用相机图像调用大模型，获取场景文字描述。

        extra_context: 额外提示词（如图像标注框信息）拼接到描述提示词末尾。
        """
        try:
            return self._dispatch_describe(cam_b64, self._provider, progress_cb, extra_context)
        except Exception as primary_exc:
            fallback = self._fallback
            if not fallback or fallback == self._provider:
                raise
            if fallback == "dashscope":
                try:
                    import dashscope  # noqa: F401
                except ImportError:
                    raise RuntimeError(
                        f"主端点 ({self._provider}) 调用失败：{primary_exc}\n"
                        f"（备用 dashscope 未安装，如需使用请 pip install dashscope）"
                    ) from primary_exc
            if progress_cb:
                progress_cb(f"\n[主端点失败，尝试备用 {fallback}...]\n")
            return self._dispatch_describe(cam_b64, fallback, progress_cb, extra_context)

    # ── provider dispatch ────────────────────────────────────────────────────

    def _dispatch(
        self,
        cam_b64: str,
        map_b64: str,
        provider: str,
        progress_cb: "Callable[[str], None] | None",
    ) -> list[dict]:
        if provider in ("local", "openai"):
            return self._query_openai_compat(cam_b64, map_b64, progress_cb)
        elif provider == "dashscope":
            return self._query_dashscope(cam_b64, map_b64, progress_cb)
        elif provider == "anthropic":
            return self._query_anthropic(cam_b64, map_b64, progress_cb)
        else:
            raise ValueError(f"Unknown VLM provider: {provider!r}")

    def _dispatch_describe(
        self,
        cam_b64: str,
        provider: str,
        progress_cb: "Callable[[str], None] | None",
        extra_context: str = "",
    ) -> str:
        if provider in ("local", "openai"):
            return self._describe_openai_compat(cam_b64, progress_cb, extra_context)
        elif provider == "dashscope":
            return self._describe_dashscope(cam_b64, progress_cb, extra_context)
        elif provider == "anthropic":
            return self._describe_anthropic(cam_b64, progress_cb, extra_context)
        else:
            raise ValueError(f"Unknown VLM provider: {provider!r}")

    def _describe_openai_compat(
        self,
        cam_b64: str,
        progress_cb: "Callable[[str], None] | None",
        extra_context: str = "",
    ) -> str:
        from openai import OpenAI  # type: ignore[import]
        client = OpenAI(base_url=self._endpoint, api_key=self._api_key or "EMPTY")
        prompt = _DESCRIBE_PROMPT + (f"\n{extra_context}" if extra_context else "")
        self._cb(progress_cb, "[AI图像描述]\n")
        description = ""
        for chunk in client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "图1（相机照片）:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{cam_b64}"}},
                    {"type": "text", "text": prompt},
                ]},
            ],
            max_tokens=512,
            temperature=0.2,
            stream=True,
        ):
            delta = chunk.choices[0].delta.content or ""
            description += delta
            self._cb(progress_cb, delta)
        self._cb(progress_cb, "\n")
        return description

    def _describe_dashscope(
        self,
        cam_b64: str,
        progress_cb: "Callable[[str], None] | None",
        extra_context: str = "",
    ) -> str:
        try:
            import dashscope  # type: ignore[import]
            from dashscope import MultiModalConversation  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "dashscope package not installed. Run: pip install dashscope"
            ) from exc
        dashscope.api_key = self._api_key
        prompt = _DESCRIBE_PROMPT + (f"\n{extra_context}" if extra_context else "")
        self._cb(progress_cb, "[AI图像描述]\n")
        resp = MultiModalConversation.call(
            model=self._model,
            messages=[{"role": "user", "content": [
                {"image": f"data:image/jpeg;base64,{cam_b64}"},
                {"text": prompt},
            ]}],
        )
        text = resp.output.choices[0].message.content[0].get("text", "")
        self._cb(progress_cb, text + "\n")
        return text

    def _describe_anthropic(
        self,
        cam_b64: str,
        progress_cb: "Callable[[str], None] | None",
        extra_context: str = "",
    ) -> str:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc
        client = anthropic.Anthropic(api_key=self._api_key)
        prompt = _DESCRIBE_PROMPT + (f"\n{extra_context}" if extra_context else "")
        self._cb(progress_cb, "[AI图像描述]\n")
        description = ""
        with client.messages.stream(
            model=self._model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "图1（相机照片）:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": cam_b64}},
                {"type": "text", "text": prompt},
            ]}],
        ) as s:
            for text in s.text_stream:
                description += text
                self._cb(progress_cb, text)
        self._cb(progress_cb, "\n")
        return description

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cb(progress_cb, text: str) -> None:
        if progress_cb:
            try:
                progress_cb(text)
            except Exception:
                pass

    def _query_openai_compat(
        self,
        cam_b64: str,
        map_b64: str,
        progress_cb: "Callable[[str], None] | None",
    ) -> list[dict]:
        from openai import OpenAI  # type: ignore[import]

        client = OpenAI(
            base_url=self._endpoint,
            api_key=self._api_key or "EMPTY",
        )
        cam_content = [
            {"type": "text", "text": "图1（相机照片）:"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{cam_b64}"}},
        ]
        map_content = [
            {"type": "text", "text": "图2（卫星地图）:"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{map_b64}"}},
        ]

        # ── Step 1: describe camera image (streaming) ──────────────────────
        self._cb(progress_cb, "[第1步] 正在描述相机图像...\n")
        description = ""
        for chunk in client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": cam_content + [{"type": "text", "text": _DESCRIBE_PROMPT}]},
            ],
            max_tokens=512,
            temperature=0.2,
            stream=True,
        ):
            delta = chunk.choices[0].delta.content or ""
            description += delta
            self._cb(progress_cb, delta)
        self._cb(progress_cb, "\n")

        # ── Step 2: locate on map (streaming) ─────────────────────────────
        self._cb(progress_cb, "\n[第2步] 正在卫星图中定位障碍物...\n")
        location_text = ""
        for chunk in client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": cam_content + map_content + [{"type": "text", "text": _LOCATE_PROMPT}]},
                {"role": "assistant", "content": f"根据图1描述：{description}\n"},
            ],
            max_tokens=512,
            temperature=0.1,
            stream=True,
        ):
            delta = chunk.choices[0].delta.content or ""
            location_text += delta
            self._cb(progress_cb, delta)
        self._cb(progress_cb, "\n")

        return self._parse(location_text)

    def _query_dashscope(
        self,
        cam_b64: str,
        map_b64: str,
        progress_cb: "Callable[[str], None] | None",
    ) -> list[dict]:
        try:
            import dashscope  # type: ignore[import]
            from dashscope import MultiModalConversation  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "dashscope package not installed. Run: pip install dashscope"
            ) from exc

        dashscope.api_key = self._api_key

        # Step 1: describe
        self._cb(progress_cb, "[第1步] 正在描述相机图像...\n")
        resp1 = MultiModalConversation.call(
            model=self._model,
            messages=[{"role": "user", "content": [
                {"image": f"data:image/jpeg;base64,{cam_b64}"},
                {"text": _DESCRIBE_PROMPT},
            ]}],
        )
        description = resp1.output.choices[0].message.content[0].get("text", "")
        self._cb(progress_cb, description + "\n")

        # Step 2: locate
        self._cb(progress_cb, "\n[第2步] 正在卫星图中定位障碍物...\n")
        resp2 = MultiModalConversation.call(
            model=self._model,
            messages=[{"role": "user", "content": [
                {"image": f"data:image/jpeg;base64,{cam_b64}"},
                {"image": f"data:image/jpeg;base64,{map_b64}"},
                {"text": _SYSTEM_PROMPT + "\n" + _LOCATE_PROMPT},
            ]}],
        )
        text = resp2.output.choices[0].message.content[0].get("text", "")
        self._cb(progress_cb, text + "\n")
        return self._parse(text)

    def _query_anthropic(
        self,
        cam_b64: str,
        map_b64: str,
        progress_cb: "Callable[[str], None] | None",
    ) -> list[dict]:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        cam_content = [
            {"type": "text", "text": "图1（相机照片）:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": cam_b64}},
        ]
        map_content = [
            {"type": "text", "text": "图2（卫星地图）:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": map_b64}},
        ]

        # Step 1: describe (streaming)
        self._cb(progress_cb, "[第1步] 正在描述相机图像...\n")
        description = ""
        with client.messages.stream(
            model=self._model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": cam_content + [{"type": "text", "text": _DESCRIBE_PROMPT}]}],
        ) as s:
            for text in s.text_stream:
                description += text
                self._cb(progress_cb, text)
        self._cb(progress_cb, "\n")

        # Step 2: locate (streaming)
        self._cb(progress_cb, "\n[第2步] 正在卫星图中定位障碍物...\n")
        location_text = ""
        with client.messages.stream(
            model=self._model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": cam_content + map_content + [{"type": "text", "text": _LOCATE_PROMPT}]},
                {"role": "assistant", "content": f"根据图1描述：{description}\n"},
            ],
        ) as s:
            for text in s.text_stream:
                location_text += text
                self._cb(progress_cb, text)
        self._cb(progress_cb, "\n")
        return self._parse(location_text)

    # ── response parsing ─────────────────────────────────────────────────────

    @staticmethod
    def _parse(text: str) -> list[dict]:
        """Extract a JSON array from the VLM response (even if wrapped in prose)."""
        text = text.strip()
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start < 0 or end <= start:
            logger.warning("VLMMapQuery: no JSON array in response: %s", text[:200])
            return []
        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            logger.warning("VLMMapQuery: JSON parse error: %s\n%s", exc, text[:500])
            return []

        result: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                result.append(
                    {
                        "label": str(item.get("label", "障碍物")),
                        "x1": float(item["x1"]),
                        "y1": float(item["y1"]),
                        "x2": float(item["x2"]),
                        "y2": float(item["y2"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                pass
        return result
