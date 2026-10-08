"""Unit tests for User Intent Ledger assembly.

Tests:
- Extraction of genuine human messages and multimodal text parts
- Strict exclusion of synthetic runtime messages (restore, subagent, memory board)
- Explicit placeholder `[no user message visible]` on empty history
- Budget preservation with initial anchor retention, omission markers, and latest directives
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.approval.intent_ledger import (
    NO_USER_MESSAGE_VISIBLE,
    OMITTED_MARKER,
    extract_user_intent_ledger,
    is_user_authored_human_message,
)


def test_intent_ledger_basic_extraction() -> None:
    msgs = [
        HumanMessage(content="First user instruction: clean up the workspace."),
        AIMessage(content="Understood, looking at files now."),
        HumanMessage(content="Second directive: do not delete the test folder."),
    ]
    result = extract_user_intent_ledger(msgs, max_chars=1000)
    assert "First user instruction: clean up the workspace." in result
    assert "Second directive: do not delete the test folder." in result
    assert "Understood, looking at files now." not in result


def test_intent_ledger_multimodal_text_extraction() -> None:
    # Multimodal message with text and image block
    multimodal_content = [
        {"type": "text", "text": "Inspect the screenshot and"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        {"type": "text", "text": "do not run build commands yet."},
    ]
    msgs = [HumanMessage(content=multimodal_content)]
    result = extract_user_intent_ledger(msgs, max_chars=1000)
    assert "Inspect the screenshot and do not run build commands yet." in result


def test_intent_ledger_synthetic_message_exclusion() -> None:
    synthetic_msg = HumanMessage(
        content="[RESTORE_NOTIFICATION] Restored 3 files from checkpoint.",
        additional_kwargs={"is_system_synthetic": True},
    )
    system_runtime_msg = HumanMessage(
        content="[WORKING_MEMORY_BOARD] Goals: None",
        additional_kwargs={"source": "runtime"},
    )
    real_user_msg = HumanMessage(content="User command: list directory.")

    msgs = [synthetic_msg, system_runtime_msg, real_user_msg]
    assert not is_user_authored_human_message(synthetic_msg)
    assert not is_user_authored_human_message(system_runtime_msg)
    assert is_user_authored_human_message(real_user_msg)

    result = extract_user_intent_ledger(msgs, max_chars=1000)
    assert "[RESTORE_NOTIFICATION]" not in result
    assert "[WORKING_MEMORY_BOARD]" not in result
    assert result == "User command: list directory."


def test_intent_ledger_empty_history_returns_explicit_placeholder() -> None:
    # When conversation only has AI and Tool messages
    msgs = [
        AIMessage(content="Thinking..."),
        ToolMessage(content="result 1", tool_call_id="tc_1"),
    ]
    result = extract_user_intent_ledger(msgs, max_chars=1000)
    assert result == NO_USER_MESSAGE_VISIBLE


def test_intent_ledger_budget_truncation_preserves_anchor_and_latest() -> None:
    # Anchor: first message
    m1 = HumanMessage(content="ANCHOR: Initial project goal and hard boundary: never push.")
    # Middle messages (old)
    m2 = HumanMessage(content="Old message 1: check git status.")
    m3 = HumanMessage(content="Old message 2: inspect diff.")
    m4 = HumanMessage(content="Old message 3: run git log.")
    # Latest directive
    m5 = HumanMessage(content="LATEST: Do NOT install any packages or touch pyproject.toml.")

    msgs = [m1, m2, m3, m4, m5]

    # Limit budget so middle messages must be omitted
    budget = 140
    result = extract_user_intent_ledger(msgs, max_chars=budget)

    # 1. Anchor must be present
    assert "ANCHOR: Initial project goal and hard boundary: never push." in result
    # 2. Omitted marker must be present
    assert OMITTED_MARKER in result
    # 3. Latest message must be present
    assert "LATEST: Do NOT install any packages or touch pyproject.toml." in result
    # 4. Old intermediate messages must be omitted
    assert "Old message 1" not in result
    assert "Old message 2" not in result


def test_intent_ledger_survives_extended_tool_calls() -> None:
    # User states a boundary in turn 0
    msgs = [
        HumanMessage(content="BOUNDARY: Do NOT run pytest until I say so.")
    ]
    # Simulate 12 turns of tool calls (AIMessage + ToolMessage)
    for i in range(12):
        msgs.append(AIMessage(content=f"Calling tool {i}"))
        msgs.append(ToolMessage(content=f"Tool output {i}", tool_call_id=f"call_{i}"))

    # Intent ledger must still retain the boundary even though message index is 25
    result = extract_user_intent_ledger(msgs, max_chars=1000)
    assert "BOUNDARY: Do NOT run pytest until I say so." in result
