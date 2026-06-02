"""Tests for HeartbeatEvaluator."""

from myrm_agent_harness.agent.skills.evolution.review.evaluator import HeartbeatConfig, HeartbeatEvaluator


def test_evaluator_suppressed_too_complex() -> None:
    evaluator = HeartbeatEvaluator(HeartbeatConfig(max_tool_calls=10))
    # Too complex: 11 tool calls > 10
    assert not evaluator.should_trigger_review(11, 100)


def test_evaluator_deep_interaction() -> None:
    evaluator = HeartbeatEvaluator(HeartbeatConfig(min_tool_calls=2, min_expression_length=50))
    # Normal complex: 51 chars >= 50, 2 tool calls >= 2
    assert evaluator.should_trigger_review(2, 51)


def test_evaluator_short_command_high_complexity() -> None:
    evaluator = HeartbeatEvaluator(HeartbeatConfig(min_tool_calls=2, min_expression_length=50))
    # Short but highly complex: 10 chars < 50, but 4 tool calls >= max(4, min_tool_calls+2)
    assert evaluator.should_trigger_review(4, 10)


def test_evaluator_not_triggered_low_expr_low_complexity() -> None:
    evaluator = HeartbeatEvaluator(HeartbeatConfig(min_tool_calls=2, min_expression_length=50))
    # 10 chars < 50, 2 tool calls < 4 -> Not complex enough for short command
    assert not evaluator.should_trigger_review(2, 10)


def test_evaluator_not_triggered_high_expr_no_tools() -> None:
    evaluator = HeartbeatEvaluator(HeartbeatConfig(min_tool_calls=2, min_expression_length=50))
    # 100 chars >= 50, but 1 tool call < 2 -> Just chatting, no real tools used
    assert not evaluator.should_trigger_review(1, 100)


def test_evaluator_default_config() -> None:
    evaluator = HeartbeatEvaluator()
    assert evaluator.config.min_tool_calls == 2
    assert evaluator.config.min_expression_length == 50
    assert evaluator.config.max_tool_calls == 50

    assert evaluator.should_trigger_review(2, 50)
    assert not evaluator.should_trigger_review(1, 50)
