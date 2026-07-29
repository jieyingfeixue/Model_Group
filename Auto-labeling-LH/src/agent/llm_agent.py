"""LLM Agent — Claude 4 Sonnet with Anthropic Tool Use protocol."""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

from src.core.types import AgentAction, RuleResult, Label3D
from .tool_executor import FrameContext, execute_tool

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个 3D 目标标注质量审查专家。你的任务是审查当前帧的所有 3D 标注框，并给出调整建议。

你可以调用以下工具获取详细信息并执行调整：
- get_box_info: 查看框的详细参数和传感器支持情况
- get_nearby_boxes: 查看周围框，检查重叠和关系
- get_lidar_cluster_stats: 分析框内点云分布
- get_radar_power_in_box: 检查雷达回波强度
- adjust_box: 调整框参数
- delete_box: 删除误检框
- confirm_box: 确认框质量合格
- refit_box_to_lidar: 重新进行点云拟合
- get_temporal_context: 检查时序一致性

审查原则：
1. 框应紧密包裹目标点云，不要过大或过小
2. 航向角应与目标运动方向或朝向一致
3. 框底面应贴近地面，不应穿入地面
4. 相同类别的目标尺寸应合理
5. 高重叠的框应合并或删除低置信度的
6. 远距离目标 (>50m) 的点云稀疏是正常的
7. 每个 adjust_box 调用必须包含 reason

对于每个框的决定，给出置信度 (0-1)：
- >= 0.85: 高置信度，可以自动执行
- 0.5-0.85: 中置信度，建议人工确认
- < 0.5: 低置信度，仅做提示"""


_TOOLS = [
    {
        "name": "get_box_info",
        "description": "获取指定标注框的详细信息，包括 3D 位置、尺寸、类别、框内 LiDAR 点数、radar 功率统计",
        "input_schema": {
            "type": "object",
            "properties": {"box_id": {"type": "string", "description": "标注框 ID"}},
            "required": ["box_id"],
        },
    },
    {
        "name": "get_nearby_boxes",
        "description": "获取指定框周围一定半径内的其他标注框",
        "input_schema": {
            "type": "object",
            "properties": {
                "box_id": {"type": "string"},
                "radius": {"type": "number", "description": "搜索半径 (米)"},
            },
            "required": ["box_id"],
        },
    },
    {
        "name": "get_lidar_cluster_stats",
        "description": "获取框内 LiDAR 点云的聚类分析：点数、分布、主轴方向、边界",
        "input_schema": {
            "type": "object",
            "properties": {
                "box_id": {"type": "string"},
                "expand_ratio": {"type": "number", "default": 1.0},
            },
            "required": ["box_id"],
        },
    },
    {
        "name": "get_radar_power_in_box",
        "description": "获取框在 4D radar 张量中的功率统计",
        "input_schema": {
            "type": "object",
            "properties": {"box_id": {"type": "string"}},
            "required": ["box_id"],
        },
    },
    {
        "name": "adjust_box",
        "description": "调整标注框参数。可调整 center_x/y/z, length/width/height, yaw",
        "input_schema": {
            "type": "object",
            "properties": {
                "box_id": {"type": "string"},
                "adjustments": {
                    "type": "object",
                    "properties": {
                        "center_x": {"type": "number"},
                        "center_y": {"type": "number"},
                        "center_z": {"type": "number"},
                        "length": {"type": "number"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "yaw": {"type": "number"},
                    },
                },
                "reason": {"type": "string", "description": "调整原因"},
            },
            "required": ["box_id", "adjustments", "reason"],
        },
    },
    {
        "name": "delete_box",
        "description": "标记一个框为应删除 (误检)",
        "input_schema": {
            "type": "object",
            "properties": {
                "box_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["box_id", "reason"],
        },
    },
    {
        "name": "confirm_box",
        "description": "确认一个框的标注质量合格",
        "input_schema": {
            "type": "object",
            "properties": {"box_id": {"type": "string"}},
            "required": ["box_id"],
        },
    },
    {
        "name": "refit_box_to_lidar",
        "description": "重新用 LiDAR 点云拟合框",
        "input_schema": {
            "type": "object",
            "properties": {"box_id": {"type": "string"}},
            "required": ["box_id"],
        },
    },
    {
        "name": "get_frame_summary",
        "description": "获取整帧标注概况",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_temporal_context",
        "description": "获取前后帧中同一目标的标注",
        "input_schema": {
            "type": "object",
            "properties": {
                "box_id": {"type": "string"},
                "window": {"type": "integer", "default": 3},
            },
            "required": ["box_id"],
        },
    },
]


class LLMAgent:
    """Claude 4 Sonnet LLM agent with tool-use for annotation review."""

    def __init__(self, config: dict[str, Any]):
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.max_rounds = config.get("max_tool_rounds", 20)
        self.temperature = config.get("temperature", 0.1)
        self._api_key = config.get("api_key", "")
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        except ImportError:
            logger.error("anthropic package not installed")
            raise

    async def review_frame(
        self, ctx: FrameContext, rule_results: list[RuleResult]
    ) -> list[AgentAction]:
        """Review all boxes via multi-round tool calling."""
        self._ensure_client()
        user_msg = _build_review_prompt(ctx, rule_results)
        messages: list[dict] = [{"role": "user", "content": user_msg}]
        actions: list[AgentAction] = []

        for _ in range(self.max_rounds):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=_SYSTEM_PROMPT,
                    tools=_TOOLS,
                    messages=messages,
                    temperature=self.temperature,
                )
            except Exception as exc:
                logger.error("LLM API call failed: %s", exc)
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = execute_tool(block.name, block.input, ctx)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                        if block.name in ("adjust_box", "delete_box", "confirm_box"):
                            actions.append(_parse_action(block.name, block.input))
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return actions


def _build_review_prompt(ctx: FrameContext, rules: list[RuleResult]) -> str:
    lines = [
        f"## 当前帧: 序列 {ctx.seq_id}, 帧 {ctx.frame_id}",
        f"总共 {len(ctx.boxes)} 个标注框",
        "",
        "### 规则引擎预检查结果:",
    ]
    for r in rules:
        if r.severity not in ("ok", "skip"):
            lines.append(f"- [{r.severity}] {r.rule} (box {r.box_id}): {r.message}")
    lines.append("")
    lines.append("### 标注框列表:")
    for box in ctx.boxes:
        lines.append(
            f"- {box.object_id}: {box.class_name}, "
            f"center=({box.center[0]:.1f}, {box.center[1]:.1f}, {box.center[2]:.1f}), "
            f"size=({box.dimensions[0]:.1f}, {box.dimensions[1]:.1f}, {box.dimensions[2]:.1f}), "
            f"yaw={np.rad2deg(box.rotation):.0f}°, score={box.score:.2f}, source={box.source}"
        )
    lines.append("")
    lines.append("请逐框审查，调用工具获取详细信息。对有问题的框调用 adjust_box 或 delete_box，对合格的框调用 confirm_box。")
    return "\n".join(lines)


def _parse_action(tool_name: str, params: dict) -> AgentAction:
    if tool_name == "adjust_box":
        return AgentAction(
            box_id=params["box_id"],
            action_type="adjust",
            confidence=0.75,
            changes=params.get("adjustments", {}),
            reason=params.get("reason", ""),
        )
    elif tool_name == "delete_box":
        return AgentAction(
            box_id=params["box_id"],
            action_type="delete",
            confidence=0.8,
            reason=params.get("reason", ""),
        )
    elif tool_name == "confirm_box":
        return AgentAction(
            box_id=params["box_id"],
            action_type="confirm",
            confidence=0.9,
        )
    return AgentAction(box_id=params.get("box_id", ""))
