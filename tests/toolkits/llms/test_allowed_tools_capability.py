"""Tests for allowed_tools provider capability helpers."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.allowed_tools_capability import (
    CAPABILITY_REJECTS_ALLOWED_TOOLS,
    model_supports_allowed_tools_tool_choice,
)
from myrm_agent_harness.toolkits.llms.capability_learner import get_capability_learner


def test_openai_like_models_default_to_unsupported() -> None:
    learner = get_capability_learner()
    learner.clear()
    assert model_supports_allowed_tools_tool_choice("openai-like/agnes-2.5-flash") is False


def test_minimax_models_default_to_unsupported() -> None:
    learner = get_capability_learner()
    learner.clear()
    assert model_supports_allowed_tools_tool_choice("minimax/MiniMax-M3") is False
    assert model_supports_allowed_tools_tool_choice(
        "MiniMax-M2.7",
        api_base="https://api.minimaxi.com/v1",
    ) is False


def test_native_openai_model_supported_by_default() -> None:
    learner = get_capability_learner()
    learner.clear()
    assert model_supports_allowed_tools_tool_choice("gpt-4o") is True


def test_learned_rejection_blocks_supported_models() -> None:
    learner = get_capability_learner()
    learner.clear()
    try:
        learner.learn("gpt-4o", CAPABILITY_REJECTS_ALLOWED_TOOLS, True)
        assert model_supports_allowed_tools_tool_choice("gpt-4o") is False
    finally:
        learner.clear()


def test_learned_rejection_is_case_insensitive() -> None:
    from myrm_agent_harness.toolkits.llms.allowed_tools_capability import (
        normalize_model_capability_key,
    )

    learner = get_capability_learner()
    learner.clear()
    try:
        learner.learn(normalize_model_capability_key("GPT-4o"), CAPABILITY_REJECTS_ALLOWED_TOOLS, True)
        assert model_supports_allowed_tools_tool_choice("gpt-4o") is False
    finally:
        learner.clear()
