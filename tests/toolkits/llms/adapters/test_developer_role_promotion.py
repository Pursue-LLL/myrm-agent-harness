"""Tests for developer role promotion in ChatLiteLLM.

Verifies that system messages are promoted to developer role for OpenAI GPT-5+,
Codex, and o-series models, while remaining unchanged for other models.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import (
    _DEVELOPER_ROLE_PATTERN,
    ChatLiteLLM,
)


def _make_model(model: str, **kwargs) -> ChatLiteLLM:
    return ChatLiteLLM.model_construct(
        client=MagicMock(), model=model, **kwargs
    )


class TestDeveloperRolePattern:
    """Verify the compiled regex matches expected model families."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-5",
            "gpt-5-chat",
            "gpt-5-mini",
            "gpt-5.1-codex",
            "gpt-5.2",
            "gpt-5.5",
            "gpt-6",
            "gpt-7",
            "gpt-9",
            "gpt-10",
            "gpt-15",
            "codex",
            "codex-mini-latest",
            "o1",
            "o1-mini",
            "o1-preview",
            "o3",
            "o3-mini",
            "o3-pro",
            "o4-mini",
            "o5",
            "o6",
            "o99",
        ],
    )
    def test_pattern_matches_developer_role_models(self, model_name: str) -> None:
        assert _DEVELOPER_ROLE_PATTERN.match(model_name), (
            f"Expected pattern to match '{model_name}'"
        )

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-4.1",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4",
            "gpt-3.5-turbo",
            "claude-3.5-sonnet",
            "deepseek-r1",
            "qwen-72b",
            "o0",
            "ollama",
            "openhermes",
            "omni-v2",
            "",
            "minimax-abab",
        ],
    )
    def test_pattern_rejects_non_developer_role_models(self, model_name: str) -> None:
        assert not _DEVELOPER_ROLE_PATTERN.match(model_name), (
            f"Expected pattern to NOT match '{model_name}'"
        )


class TestShouldPromoteSystemToDeveloper:
    """Verify the promotion decision logic on ChatLiteLLM instances."""

    def test_promotes_for_gpt5(self) -> None:
        model = _make_model("gpt-5-chat")
        assert model._should_promote_system_to_developer() is True

    def test_promotes_for_codex(self) -> None:
        model = _make_model("codex-mini-latest")
        assert model._should_promote_system_to_developer() is True

    def test_promotes_for_o3(self) -> None:
        model = _make_model("o3-mini")
        assert model._should_promote_system_to_developer() is True

    def test_promotes_for_o4(self) -> None:
        model = _make_model("o4-mini")
        assert model._should_promote_system_to_developer() is True

    def test_promotes_for_o1(self) -> None:
        model = _make_model("o1-preview")
        assert model._should_promote_system_to_developer() is True

    def test_no_promote_for_gpt4(self) -> None:
        model = _make_model("gpt-4o-mini")
        assert model._should_promote_system_to_developer() is False

    def test_no_promote_for_claude(self) -> None:
        model = _make_model("claude-3.5-sonnet")
        assert model._should_promote_system_to_developer() is False

    def test_no_promote_for_deepseek(self) -> None:
        model = _make_model("deepseek-r1")
        assert model._should_promote_system_to_developer() is False

    def test_provider_prefix_stripped(self) -> None:
        model = _make_model("openai/gpt-5-chat")
        assert model._should_promote_system_to_developer() is True

    def test_azure_provider_prefix(self) -> None:
        model = _make_model("azure/gpt-5")
        assert model._should_promote_system_to_developer() is True

    def test_double_provider_prefix(self) -> None:
        model = _make_model("openrouter/openai/gpt-5")
        assert model._should_promote_system_to_developer() is True

    def test_mutual_exclusion_with_minimax(self) -> None:
        """MiniMax demotion takes priority; promotion should NOT trigger."""
        model = _make_model(
            "minimax/gpt-5",
            api_base="https://api.minimaxi.com/v1",
            custom_llm_provider="minimax",
        )
        assert model._should_promote_system_to_developer() is False

    def test_empty_model_name(self) -> None:
        model = _make_model("")
        assert model._should_promote_system_to_developer() is False

    def test_future_gpt6(self) -> None:
        model = _make_model("gpt-6-turbo")
        assert model._should_promote_system_to_developer() is True

    def test_future_o5(self) -> None:
        model = _make_model("o5-pro")
        assert model._should_promote_system_to_developer() is True

    def test_case_insensitive_gpt5(self) -> None:
        model = _make_model("GPT-5-Chat")
        assert model._should_promote_system_to_developer() is True

    def test_case_insensitive_codex(self) -> None:
        model = _make_model("CODEX-mini")
        assert model._should_promote_system_to_developer() is True

    def test_model_name_fallback(self) -> None:
        """When model is empty, should fall back to model_name attribute."""
        model = _make_model("", model_name="gpt-5-chat")
        assert model._should_promote_system_to_developer() is True

    def test_model_name_fallback_no_promote(self) -> None:
        model = _make_model("", model_name="gpt-4o")
        assert model._should_promote_system_to_developer() is False

    def test_codex_with_version_suffix(self) -> None:
        model = _make_model("codex-2")
        assert model._should_promote_system_to_developer() is True


class TestCreateMessageDictsPromotion:
    """Verify that _create_message_dicts actually promotes system→developer."""

    def test_gpt5_promotes_first_system_to_developer(self) -> None:
        model = _make_model("gpt-5-chat")
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "developer"
        assert message_dicts[0]["content"] == "You are helpful."
        assert message_dicts[1]["role"] == "user"

    def test_codex_promotes_first_system_to_developer(self) -> None:
        model = _make_model("codex-mini-latest")
        messages = [
            SystemMessage(content="System instructions."),
            HumanMessage(content="Write code."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "developer"

    def test_gpt4_keeps_system_unchanged(self) -> None:
        model = _make_model("gpt-4o-mini")
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "system"

    def test_no_messages_does_not_crash(self) -> None:
        model = _make_model("gpt-5-chat")
        message_dicts, _ = model._create_message_dicts([], stop=None)
        assert message_dicts == []

    def test_first_message_not_system_stays_unchanged(self) -> None:
        model = _make_model("gpt-5-chat")
        messages = [
            HumanMessage(content="Hello"),
            SystemMessage(content="Late system."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "user"
        assert message_dicts[1]["role"] == "system"

    def test_subsequent_system_messages_not_promoted(self) -> None:
        """Only the first message should be promoted; later system messages stay."""
        model = _make_model("gpt-5-chat")
        messages = [
            SystemMessage(content="Main prompt."),
            HumanMessage(content="Hello"),
            SystemMessage(content="Plugin instruction."),
            AIMessage(content="Response."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "developer"
        assert message_dicts[2]["role"] == "system"

    def test_provider_prefix_gpt5_promotes(self) -> None:
        model = _make_model("openai/gpt-5")
        messages = [
            SystemMessage(content="Instructions."),
            HumanMessage(content="Query."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "developer"

    def test_minimax_demotes_not_promotes(self) -> None:
        """MiniMax path should demote, not promote."""
        model = _make_model(
            "minimax/MiniMax-M2.5",
            api_base="https://api.minimaxi.com/v1",
            custom_llm_provider="minimax",
        )
        messages = [
            SystemMessage(content="Instructions."),
            HumanMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)

        assert message_dicts[0]["role"] == "user"
        assert "developer" not in [d["role"] for d in message_dicts]

    def test_promotion_with_stop_param(self) -> None:
        """stop parameter should not interfere with promotion logic."""
        model = _make_model("gpt-5")
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hello"),
        ]
        message_dicts, params = model._create_message_dicts(
            messages, stop=["STOP"]
        )
        assert message_dicts[0]["role"] == "developer"
        assert params["stop"] == ["STOP"]

    def test_case_insensitive_promotion_in_message_dicts(self) -> None:
        model = _make_model("GPT-5")
        messages = [
            SystemMessage(content="Instructions."),
            HumanMessage(content="Query."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assert message_dicts[0]["role"] == "developer"

    def test_o3_promotes_in_message_dicts(self) -> None:
        model = _make_model("o3-mini")
        messages = [
            SystemMessage(content="Be concise."),
            HumanMessage(content="Summarize."),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assert message_dicts[0]["role"] == "developer"
        assert message_dicts[0]["content"] == "Be concise."
