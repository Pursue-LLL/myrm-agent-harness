"""Tests for goal prompt prefix SSOT constants."""

from myrm_agent_harness.agent.goals.goal_prompt_prefixes import (
    GOAL_CONTINUATION_PREFIX,
    GOAL_WRAPUP_PREFIX,
)


def test_goal_continuation_prefix_value() -> None:
    assert GOAL_CONTINUATION_PREFIX == "[Continuing toward your standing goal]"


def test_goal_wrapup_prefix_value() -> None:
    assert GOAL_WRAPUP_PREFIX == "[Budget reached — wrap-up turn]"
