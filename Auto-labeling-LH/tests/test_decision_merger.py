"""Tests for the decision merger."""

from __future__ import annotations

from src.core.types import AgentAction, FinalDecision, RuleResult, AutoAction, VisionVerification
from src.agent.decision_merger import DecisionMerger


def test_auto_execution_high_confidence():
    merger = DecisionMerger()
    rules = [
        RuleResult(
            rule="ground_penetration", severity="warning",
            message="穿入地面 0.5m", box_id="b1",
            auto_action=AutoAction(type="adjust_center_z", value=1.0, confidence=0.9),
        )
    ]
    decisions = merger.merge(rules, [], [])
    assert len(decisions) == 1
    assert decisions[0].execution_mode == "auto"
    assert decisions[0].action == "adjust"


def test_ask_human_medium_confidence():
    merger = DecisionMerger()
    rules = [
        RuleResult(
            rule="dimension_prior", severity="warning",
            message="尺寸偏大", box_id="b1",
            auto_action=AutoAction(type="adjust_dimensions", value=[4.0, 1.8, 1.5], confidence=0.7),
        )
    ]
    decisions = merger.merge(rules, [], [])
    assert len(decisions) == 1
    assert decisions[0].execution_mode == "ask_human"


def test_llm_delete_action():
    merger = DecisionMerger()
    llm_actions = [
        AgentAction(box_id="b1", action_type="delete", confidence=0.85, reason="误检")
    ]
    decisions = merger.merge([], llm_actions, [])
    assert len(decisions) == 1
    assert decisions[0].action == "delete"
    assert decisions[0].execution_mode == "auto"


def test_vision_disagreement_lowers_confidence():
    merger = DecisionMerger()
    llm_actions = [
        AgentAction(box_id="b1", action_type="adjust", confidence=0.8, changes={"center_z": 1.0})
    ]
    vision = [
        VisionVerification(box_id="b1", alignment="shift_left", class_correct=False, suggested_class="truck")
    ]
    decisions = merger.merge([], llm_actions, vision)
    assert len(decisions) == 1
    # Confidence should be lowered due to vision disagreement
    assert decisions[0].confidence < 0.8
