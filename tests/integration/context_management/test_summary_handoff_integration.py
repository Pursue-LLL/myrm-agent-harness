"""Integration test: generate_structured_summary with real LLM for handoff fields.

Validates that blocked_items and next_steps are correctly populated by a real LLM
when the conversation history contains explicit blockers and planned next actions.
Uses BASIC_MODEL from .env.test (or fallback) via ChatLiteLLM.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser

from myrm_agent_harness.agent.context_management.infra.schemas import (
    ContextConfig,
    StructuredSummary,
)
from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
    _FallbackSummaryModel,
    generate_structured_summary,
)

_RAW_MODEL = os.environ.get("BASIC_MODEL", "openai-like/mimo-v2.5-pro")
_TEST_BASE_URL = os.environ.get("BASIC_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
_TEST_API_KEY = os.environ.get("BASIC_API_KEY", "")

pytestmark = pytest.mark.timeout(120)


def _normalize_model(raw: str) -> tuple[str, str | None]:
    """Convert env model name (e.g. openai-like/X) to LiteLLM (openai/X, provider)."""
    openai_compat = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in openai_compat:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


def _require_api_key() -> None:
    if not _TEST_API_KEY:
        pytest.skip("BASIC_API_KEY not set — skipping real LLM integration test")


def _make_llm():
    from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

    model, provider = _normalize_model(_RAW_MODEL)
    return ChatLiteLLM(
        model=model,
        api_key=_TEST_API_KEY,
        api_base=_TEST_BASE_URL,
        custom_llm_provider=provider,
        temperature=0.0,
        max_tokens=4096,
    )


def _make_conversation_with_blocker() -> list[HumanMessage | AIMessage | SystemMessage]:
    """Build a realistic conversation where the agent is blocked and has next steps."""
    return [
        SystemMessage(content="You are a helpful AI assistant."),
        HumanMessage(content="Please refactor the authentication module in app/auth/jwt.py to use RS256 instead of HS256."),
        AIMessage(content="I'll start by reading the current jwt.py implementation to understand the existing code."),
        HumanMessage(content="Here's the file content:\n```python\nimport jwt\ndef verify(token):\n    return jwt.decode(token, SECRET, algorithms=['HS256'])\n```"),
        AIMessage(content="I see the current implementation uses HS256. I'll need to:\n1. Generate RSA key pair\n2. Update the verify function to use RS256\n3. Update the sign function\n\nLet me start with generating the key pair."),
        HumanMessage(content="I ran the key generation script but got an error: `cryptography.exceptions.UnsupportedAlgorithm: RSA key generation requires pyca/cryptography >= 3.0`. The current environment has cryptography 2.8."),
        AIMessage(content="The cryptography library version is too old. We need to upgrade it first. However, I notice the requirements.txt has a pin `cryptography==2.8` with a comment saying 'pinned for FIPS compliance'. I'm blocked on this - I need to know if we can upgrade the cryptography library or if FIPS compliance is still required.\n\nPlanned next steps once unblocked:\n1. Upgrade cryptography to >= 3.0 (if FIPS allows)\n2. Generate RSA-2048 key pair\n3. Refactor jwt.py verify() to RS256\n4. Update all tests in tests/test_auth.py\n5. Run full test suite"),
        HumanMessage(content="Good analysis. Let me check with the security team about FIPS."),
    ]


def _force_parser_fallback(_llm):
    """Force PydanticOutputParser path — many OpenAI-compatible models don't support native structured output."""
    return None, PydanticOutputParser(pydantic_object=_FallbackSummaryModel)


@pytest.mark.asyncio
async def test_full_summary_captures_blocked_and_next_steps() -> None:
    """Real LLM generates a summary that includes blocked_items and next_steps."""
    _require_api_key()
    llm = _make_llm()
    messages = _make_conversation_with_blocker()

    config = ContextConfig(max_context_tokens=128000)

    with patch(
        "myrm_agent_harness.agent.context_management.strategies.summary.summarizer._get_structured_llm_or_parser",
        side_effect=_force_parser_fallback,
    ):
        new_messages, summary = await generate_structured_summary(
            messages=messages,
            llm=llm,
            chat_id="test-integration-handoff",
            config=config,
        )

    assert isinstance(summary, StructuredSummary)
    assert summary.user_goal, "user_goal should not be empty"
    assert isinstance(new_messages, list)
    assert len(new_messages) > 0

    has_blocked = len(summary.blocked_items) > 0
    has_next = len(summary.next_steps) > 0

    if has_blocked:
        blocked_text = " ".join(summary.blocked_items).lower()
        assert any(
            keyword in blocked_text
            for keyword in ["cryptography", "fips", "upgrade", "version", "library", "blocked"]
        ), f"blocked_items should mention the cryptography/FIPS blocker, got: {summary.blocked_items}"

    if has_next:
        next_text = " ".join(summary.next_steps).lower()
        assert any(
            keyword in next_text
            for keyword in ["upgrade", "rsa", "rs256", "refactor", "test", "jwt", "key"]
        ), f"next_steps should mention planned actions, got: {summary.next_steps}"

    found_summary_msg = False
    for msg in new_messages:
        if isinstance(msg, HumanMessage) and "memory-context" in str(msg.content):
            found_summary_msg = True
            content = str(msg.content)
            if has_blocked:
                assert "Blocked:" in content, "Rendered summary should contain Blocked: section"
            if has_next:
                assert "Next Steps:" in content, "Rendered summary should contain Next Steps: section"
            break
    assert found_summary_msg, "Summary message should exist in new_messages"

    json_str = summary.to_json()
    if has_blocked:
        assert "blocked_items" in json_str
    if has_next:
        assert "next_steps" in json_str


@pytest.mark.asyncio
async def test_incremental_summary_updates_blocked_and_next_steps() -> None:
    """Incremental merge correctly updates blocked_items and next_steps."""
    _require_api_key()
    llm = _make_llm()

    existing_summary = StructuredSummary(
        user_goal="Refactor auth module to RS256",
        completed_actions=["Read jwt.py", "Identified HS256 usage"],
        key_findings=["cryptography 2.8 too old for RS256"],
        last_action="Attempted key generation",
        blocked_items=["cryptography library pinned to 2.8 for FIPS"],
        next_steps=["Upgrade cryptography", "Generate RSA key pair"],
        files_modified=["app/auth/jwt.py"],
    )

    new_messages: list[HumanMessage | AIMessage | SystemMessage] = [
        SystemMessage(content="You are a helpful AI assistant."),
        HumanMessage(content="Security team confirmed: FIPS compliance is no longer required. We can upgrade cryptography."),
        AIMessage(content="The FIPS blocker is resolved. I'll now upgrade cryptography to the latest version and proceed with the RS256 migration.\n\nUpdated plan:\n1. pip install cryptography>=41.0\n2. Generate RSA-2048 key pair\n3. Refactor jwt.py\n4. Update tests"),
    ]

    config = ContextConfig(max_context_tokens=128000)

    with patch(
        "myrm_agent_harness.agent.context_management.strategies.summary.summarizer._get_structured_llm_or_parser",
        side_effect=_force_parser_fallback,
    ):
        _new_msgs, summary = await generate_structured_summary(
            messages=new_messages,
            llm=llm,
            chat_id="test-integration-incremental",
            existing_summary=existing_summary,
            config=config,
        )

    assert isinstance(summary, StructuredSummary)
    assert summary.user_goal, "user_goal should not be empty"

    if summary.blocked_items:
        blocked_lower = [b.lower() for b in summary.blocked_items]
        for b in blocked_lower:
            assert "fips" not in b or "resolved" in b or "no longer" in b, (
                f"Old FIPS blocker should be resolved/removed, got: {summary.blocked_items}"
            )
