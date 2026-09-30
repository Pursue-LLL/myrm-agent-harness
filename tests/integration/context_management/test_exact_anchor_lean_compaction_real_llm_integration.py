"""End-to-end integration test: ExactAnchorIndex & LeanCompactionEngine with real LLM.

Validates the complete production flow:
1. Real multi-turn developer chat containing code paths, commit SHAs, fatal tracebacks,
   code symbols, and dependency noise.
2. Real LLM invocation via ChatLiteLLM (.env.test credentials).
3. Deterministic ExactAnchorTable injection into preserved context with Recency-First ordering
   and build/dependency path blacklisting.
4. Lossless conversion between StructuredSummary and 4-pillar LeanStructuredSummary.
5. Historical turn refetching (in-line verbatim retrieval and zero-copy vault pointer).
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.output_parsers import PydanticOutputParser

from myrm_agent_harness.agent.context_management.infra.schemas import (
    ContextConfig,
    StructuredSummary,
)
from myrm_agent_harness.agent.context_management.strategies.summary.lean_summary import (
    LeanStructuredSummary,
)
from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
    _FallbackSummaryModel,
    generate_structured_summary,
)
from myrm_agent_harness.agent.context_management.strategies.summary.turn_refetcher import (
    refetch_historical_turn,
)

_RAW_MODEL = os.environ.get("BASIC_MODEL", "minimax/MiniMax-M3.1-Flash-Preview")
_TEST_BASE_URL = os.environ.get("BASIC_BASE_URL", "https://api.minimaxi.com/v1")
_TEST_API_KEY = os.environ.get("BASIC_API_KEY", "")

pytestmark = pytest.mark.timeout(180)


def _normalize_model(raw: str) -> tuple[str, str | None]:
    openai_compat = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in openai_compat:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


def _require_api_key() -> None:
    if not _TEST_API_KEY:
        pytest.skip("BASIC_API_KEY not set in .env.test — skipping real LLM integration test")


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


def _build_real_world_developer_session() -> list[SystemMessage | HumanMessage | AIMessage | ToolMessage]:
    """Realistic developer workflow with code modifications, fatal tracebacks, and dependency noise."""
    return [
        SystemMessage(content="You are an expert full-stack AI coding engineer."),
        HumanMessage(
            content=(
                "Please refactor the token verification in `app/auth/jwt.py` and write tests "
                "in `tests/test_auth.py` for commit c886c6eed01234567890abcdef1234567890abcd."
            )
        ),
        AIMessage(
            content=(
                "I will examine class `AuthTokenManager` and `verify_jwt_token` in `app/auth/jwt.py` "
                "and call the API endpoint `/api/v1/auth/tokens` to inspect current token behavior."
            ),
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"command": "python -m pytest app/auth/jwt.py"},
                    "id": "call_inspect_1",
                }
            ],
        ),
        ToolMessage(
            content=(
                "Traceback (most recent call last):\n"
                '  File "app/auth/jwt.py", line 42, in verify_jwt_token\n'
                '    raise InvalidTokenError("Signature verification failed")\n'
                "jwt.exceptions.InvalidTokenError: Signature verification failed"
            ),
            tool_call_id="call_inspect_1",
        ),
        HumanMessage(
            content=(
                "Also make sure not to include build noise like node_modules/jsonwebtoken/index.js "
                "or .venv/lib/python3.13/site-packages/jwt/__init__.py in our git commit."
            )
        ),
        AIMessage(
            content=(
                "Understood. The root cause is the algorithm mismatch in verify_jwt_token. "
                "I will now update `tests/test_auth.py` to fix the test suite and verify `/api/v1/users/me`."
            ),
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"command": "pytest tests/test_auth.py"},
                    "id": "call_test_1",
                }
            ],
        ),
        ToolMessage(
            content="tests/test_auth.py passed (2 tests passed in 0.05s).",
            tool_call_id="call_test_1",
        ),
    ]


def _force_parser_fallback(_llm):
    return None, PydanticOutputParser(pydantic_object=_FallbackSummaryModel)


@pytest.mark.asyncio
async def test_exact_anchor_index_and_lean_compaction_real_llm_flow() -> None:
    """End-to-end verification of ExactAnchorTable extraction, prompt cache protection,

    lean conversion, and historical turn refetching with a real model.
    """
    _require_api_key()
    llm = _make_llm()
    messages = _build_real_world_developer_session()
    config = ContextConfig(max_context_tokens=128000)

    with patch(
        "myrm_agent_harness.agent.context_management.strategies.summary.summarizer._get_structured_llm_or_parser",
        side_effect=_force_parser_fallback,
    ):
        new_messages, summary = await generate_structured_summary(
            messages=messages,
            llm=llm,
            chat_id="test-e2e-exact-anchor-chat",
            config=config,
        )

    # 1. Summary validation
    assert isinstance(summary, StructuredSummary)
    assert summary.user_goal, "user_goal must be extracted by real LLM"

    # 2. Preserved Critical Context & Exact Anchor Table validation in new_messages
    summary_messages = [m for m in new_messages if isinstance(m, HumanMessage) and "memory-context" in str(m.content)]
    assert len(summary_messages) == 1, "Exactly one summary HumanMessage should be present"

    summary_content = str(summary_messages[0].content)
    assert "[Preserved Critical Context]" in summary_content
    assert "### ⚓ Exact Anchor Index (Machine-Extracted Truth)" in summary_content
    assert "<!-- EXACT_ANCHOR_JSON:" in summary_content

    # 3. Honest Error Signatures check (not misleading "Resolved Errors")
    assert "- **Error Signatures**:" in summary_content
    assert "InvalidTokenError" in summary_content

    # 4. Critical code identifiers & commit SHA retention check
    assert "`c886c6eed01234567890abcdef1234567890abcd`" in summary_content
    assert "`app/auth/jwt.py`" in summary_content
    assert "`tests/test_auth.py`" in summary_content
    assert "`verify_jwt_token`" in summary_content
    assert "`/api/v1/auth/tokens`" in summary_content

    # 5. Dependency & build blacklist enforcement check (in exact anchor table)
    anchor_idx = summary_content.find("### ⚓ Exact Anchor Index")
    assert anchor_idx > 0, "Exact Anchor Index heading must be present"
    anchor_section = summary_content[anchor_idx:]
    assert "node_modules" not in anchor_section
    assert ".venv" not in anchor_section

    # 6. JSON Comment Parseability check (Machine-readable contract)
    json_start = summary_content.find("<!-- EXACT_ANCHOR_JSON:") + len("<!-- EXACT_ANCHOR_JSON:")
    json_end = summary_content.find("-->", json_start)
    assert json_start > 0 and json_end > json_start
    parsed_json = json.loads(summary_content[json_start:json_end].strip())
    assert "c886c6eed01234567890abcdef1234567890abcd" in parsed_json["commit_shas"]
    assert "app/auth/jwt.py" in parsed_json["file_paths"]
    assert any("InvalidTokenError" in err for err in parsed_json["error_spans"])

    # 7. 4-Pillar Lean Structured Summary conversion check
    lean = LeanStructuredSummary.from_structured_summary(summary)
    assert lean.user_goal, "Lean user_goal must be preserved"
    lean_dict = lean.to_dict()
    assert set(lean_dict.keys()) == {"user_goal", "active_state", "key_decisions", "next_steps"}

    # 8. Single-Turn Verbatim Refetcher check (Zero loss after compaction)
    # Turn #3 is the ToolMessage with the fatal InvalidTokenError traceback
    refetched_err_turn = refetch_historical_turn(messages, 3)
    assert refetched_err_turn is not None
    assert refetched_err_turn.is_vault_pointer is False
    assert "InvalidTokenError: Signature verification failed" in refetched_err_turn.content

    # Defensive vault offloading test
    vault_turn = refetch_historical_turn(messages, 3, max_inline_chars=50, chat_id="chat-vault-test")
    assert vault_turn is not None
    assert vault_turn.is_vault_pointer is True
    assert "vault://chat-vault-test/turns/3/transcript.log" in vault_turn.content
