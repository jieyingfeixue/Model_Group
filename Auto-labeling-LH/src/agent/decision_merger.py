"""Decision merger — combine rule, LLM, and vision results."""

from __future__ import annotations

import logging
from typing import Any

from src.core.types import (
    AgentAction,
    FinalDecision,
    RuleResult,
    VisionVerification,
)

logger = logging.getLogger(__name__)


class DecisionMerger:
    """Merge three layers of agent results into final decisions."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.auto_threshold = cfg.get("auto_apply_threshold", 0.85)
        self.ask_threshold = cfg.get("ask_human_threshold", 0.5)
        self.max_auto = cfg.get("max_auto_adjustments_per_frame", 10)

    def merge(
        self,
        rule_results: list[RuleResult],
        llm_actions: list[AgentAction],
        vision_results: list[VisionVerification],
    ) -> list[FinalDecision]:
        # Gather all unique box IDs
        box_ids: set[str] = set()
        for r in rule_results:
            if r.box_id:
                box_ids.add(r.box_id)
        for a in llm_actions:
            if a.box_id:
                box_ids.add(a.box_id)
        for v in vision_results:
            if v.box_id:
                box_ids.add(v.box_id)

        decisions: list[FinalDecision] = []
        auto_count = 0
        for bid in box_ids:
            rules = [r for r in rule_results if r.box_id == bid]
            llm = next((a for a in llm_actions if a.box_id == bid), None)
            vision = next((v for v in vision_results if v.box_id == bid), None)
            d = self._merge_single(bid, rules, llm, vision)
            if d.execution_mode == "auto":
                auto_count += 1
                if auto_count > self.max_auto:
                    d.execution_mode = "ask_human"
            decisions.append(d)
        return decisions

    def _merge_single(
        self,
        box_id: str,
        rules: list[RuleResult],
        llm: AgentAction | None,
        vision: VisionVerification | None,
    ) -> FinalDecision:
        # Start with rule-based decision
        rule_action = None
        rule_confidence = 0.0
        reasons: list[str] = []

        for r in rules:
            if r.severity in ("error", "warning") and r.auto_action:
                if r.auto_action.confidence > rule_confidence:
                    rule_action = r.auto_action
                    rule_confidence = r.auto_action.confidence
                reasons.append(f"[rule:{r.rule}] {r.message}")

        # LLM action
        llm_confidence = llm.confidence if llm else 0.0
        if llm and llm.reason:
            reasons.append(f"[llm] {llm.reason}")

        # Vision alignment
        vision_ok = True
        if vision:
            if vision.alignment != "good":
                vision_ok = False
                reasons.append(f"[vision] alignment={vision.alignment}")
            if not vision.class_correct:
                vision_ok = False
                reasons.append(f"[vision] class incorrect, suggest={vision.suggested_class}")

        # Determine final action and confidence
        final_action = "keep"
        final_changes: dict[str, Any] = {}
        final_confidence = 1.0
        source = "merged"

        if rule_action and rule_action.type == "delete":
            final_action = "delete"
            final_confidence = rule_confidence
            source = "rule"
        elif llm and llm.action_type == "delete":
            final_action = "delete"
            final_confidence = llm_confidence
            source = "llm"
        elif llm and llm.action_type == "adjust":
            final_action = "adjust"
            final_changes = dict(llm.changes)
            final_confidence = llm_confidence
            source = "llm"
        elif rule_action and rule_action.type.startswith("adjust"):
            final_action = "adjust"
            if rule_action.type == "adjust_dimensions":
                final_changes["dimensions"] = rule_action.value
            elif rule_action.type == "adjust_center_z":
                final_changes["center_z"] = rule_action.value
            elif rule_action.type == "adjust_yaw":
                final_changes["rotation"] = rule_action.value
            final_confidence = rule_confidence
            source = "rule"

        # Confidence boost if LLM and vision agree
        if llm and vision_ok and llm.action_type in ("confirm", "adjust"):
            final_confidence = min(final_confidence + 0.1, 1.0)
        # Confidence penalty if LLM and vision disagree
        if llm and not vision_ok:
            final_confidence = max(final_confidence - 0.15, 0.0)

        # Determine execution mode
        if final_confidence >= self.auto_threshold:
            mode = "auto"
        elif final_confidence >= self.ask_threshold:
            mode = "ask_human"
        else:
            mode = "info_only"

        return FinalDecision(
            box_id=box_id,
            action=final_action,
            confidence=final_confidence,
            execution_mode=mode,
            changes=final_changes,
            reasons=reasons,
            source=source,
        )
