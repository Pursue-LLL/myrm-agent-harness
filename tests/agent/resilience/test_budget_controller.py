"""Tests for DynamicExecutionBudgetController and quota governance."""

import time
import pytest

from myrm_agent_harness.agent.resilience.budget_controller import (
    DynamicExecutionBudgetController,
)
from myrm_agent_harness.agent.resilience.types import ExecutionBudgetConfig


def test_budget_controller_step_limit():
    config = ExecutionBudgetConfig(max_steps_per_task=5)
    controller = DynamicExecutionBudgetController(config)

    for _ in range(4):
        controller.record_step()
        assert controller.check_budget_violation() is None

    controller.record_step()  # 5th step hits limit
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Step quota exceeded" in violation


def test_budget_controller_token_limit():
    config = ExecutionBudgetConfig(max_tokens_total=1000)
    controller = DynamicExecutionBudgetController(config)

    controller.record_token_usage(prompt_tokens=400, completion_tokens=500)
    assert controller.check_budget_violation() is None

    controller.record_token_usage(prompt_tokens=100, completion_tokens=100)
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Token budget exceeded" in violation


def test_budget_controller_consecutive_errors():
    config = ExecutionBudgetConfig(max_consecutive_errors=3)
    controller = DynamicExecutionBudgetController(config)

    controller.record_error("Err 1")
    controller.record_error("Err 2")
    assert controller.check_budget_violation() is None

    controller.record_success()
    controller.record_error("Err 3")
    assert controller.check_budget_violation() is None

    controller.record_error("Err 4")
    controller.record_error("Err 5")
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Consecutive error breaker tripped" in violation


def test_budget_controller_snapshot():
    controller = DynamicExecutionBudgetController()
    controller.record_step()
    controller.record_token_usage(100, 200)
    snapshot = controller.get_snapshot()

    assert snapshot.total_steps == 1
    assert snapshot.total_tokens == 300
    assert snapshot.is_exhausted is False
