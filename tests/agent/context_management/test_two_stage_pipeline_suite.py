"""Unit tests for TwoStageContextPipelineAndProviderProtocolDecouplingSuite."""

from __future__ import annotations

import json
import pytest

from myrm_agent_harness.agent.context_management import (
    AssemblyAdjustmentDirective,
    DagEntryKind,
    LlmProviderProtocolKind,
    LogicalContextBundle,
    LogicalToolSpec,
    LogicalTurn,
    PipelineStageReceipt,
    ProviderPayloadResult,
    SessionTreeEntry,
    TwoStageContextPipelineAndProviderProtocolDecouplingSuite,
)


def test_stage_one_semantic_assembly_and_decoupling() -> None:
    """Test Stage 1 assembling high-level logical context independent of provider protocol schemas."""
    suite = TwoStageContextPipelineAndProviderProtocolDecouplingSuite(session_id="sess-pipe-001")

    system_prompts = [
        "SYSTEM_DIRECTIVE_1: You are an autonomous coding engineer.",
        "SYSTEM_DIRECTIVE_2: Always write type-safe code.",
    ]
    workspace_rules = "RULE: Single file size < 400 lines."

    tree_entries = [
        SessionTreeEntry(
            entry_id="e1",
            parent_id=None,
            kind=DagEntryKind.MESSAGE,
            session_id="sess-pipe-001",
            branch_name="main",
            created_at_iso="2026-10-08T00:00:00Z",
            payload={"role": "user", "content": "Refactor database models"},
        ),
        SessionTreeEntry(
            entry_id="e2",
            parent_id="e1",
            kind=DagEntryKind.MESSAGE,
            session_id="sess-pipe-001",
            branch_name="main",
            created_at_iso="2026-10-08T00:01:00Z",
            payload={"role": "assistant", "content": "Inspecting schema now."},
        ),
    ]

    tools = [
        LogicalToolSpec(
            name="read_file",
            description="Read file content from local disk",
            parameters_schema={"path": "string"},
        )
    ]

    bundle = suite.assemble_logical_context(
        system_prompts=system_prompts,
        workspace_rules=workspace_rules,
        tree_entries=tree_entries,
        tools=tools,
        temperature=0.2,
        max_tokens=2048,
    )

    assert isinstance(bundle, LogicalContextBundle)
    assert bundle.session_id == "sess-pipe-001"
    assert len(bundle.system_directives) == 3
    assert len(bundle.dialogue_turns) == 2
    assert bundle.dialogue_turns[0].role == "user"
    assert bundle.dialogue_turns[1].role == "assistant"
    assert len(bundle.active_tools) == 1
    assert bundle.temperature == 0.2
    assert bundle.max_tokens == 2048


def test_stage_two_multivendor_protocol_transpilation() -> None:
    """Test Stage 2 transpiling identical logical bundle into Anthropic, OpenAI, DeepSeek, and Gemini schemas."""
    suite = TwoStageContextPipelineAndProviderProtocolDecouplingSuite(session_id="sess-pipe-002")

    bundle = LogicalContextBundle(
        session_id="sess-pipe-002",
        system_directives=["System prompt alpha", "System prompt beta"],
        dialogue_turns=[
            LogicalTurn(
                turn_id="t1",
                role="user",
                content="Analyze time complexity",
            ),
            LogicalTurn(
                turn_id="t2",
                role="assistant",
                content="It is O(N log N)",
                reasoning_content="Examined sort loop and binary search step",
            ),
        ],
        active_tools=[
            LogicalToolSpec(name="benchmark", description="Run benchmark suite")
        ],
        temperature=0.5,
        max_tokens=1000,
    )

    # 1. Transpile to Anthropic
    anthropic_res, _ = suite.convert_to_provider_wire(bundle, LlmProviderProtocolKind.ANTHROPIC)
    assert anthropic_res.provider == LlmProviderProtocolKind.ANTHROPIC
    assert anthropic_res.system_prompt_mode == "top_level_param"
    assert "System prompt alpha" in anthropic_res.payload_dict["system"]
    anthropic_msgs = json.loads(anthropic_res.payload_dict["messages"])
    assert len(anthropic_msgs) == 2
    assert "tools" in anthropic_res.payload_dict

    # 2. Transpile to OpenAI
    openai_res, _ = suite.convert_to_provider_wire(bundle, LlmProviderProtocolKind.OPENAI)
    assert openai_res.provider == LlmProviderProtocolKind.OPENAI
    assert openai_res.system_prompt_mode == "developer_message"
    openai_msgs = json.loads(openai_res.payload_dict["messages"])
    # Contains 1 developer message + 2 dialogue turns = 3
    assert len(openai_msgs) == 3
    assert openai_msgs[0]["role"] == "developer"
    assert "tools" in openai_res.payload_dict

    # 3. Transpile to DeepSeek
    deepseek_res, _ = suite.convert_to_provider_wire(bundle, LlmProviderProtocolKind.DEEPSEEK)
    assert deepseek_res.provider == LlmProviderProtocolKind.DEEPSEEK
    deepseek_msgs = json.loads(deepseek_res.payload_dict["messages"])
    assert deepseek_msgs[0]["role"] == "system"
    # Verify reasoning_content preserved for deep reasoning model
    assert deepseek_msgs[2]["reasoning_content"] == "Examined sort loop and binary search step"

    # 4. Transpile to Gemini
    gemini_res, _ = suite.convert_to_provider_wire(bundle, LlmProviderProtocolKind.GEMINI)
    assert gemini_res.provider == LlmProviderProtocolKind.GEMINI
    assert gemini_res.system_prompt_mode == "system_instruction"
    gemini_contents = json.loads(gemini_res.payload_dict["contents"])
    assert len(gemini_contents) == 2
    assert gemini_contents[0]["role"] == "user"
    assert gemini_contents[1]["role"] == "model"


def test_reverse_backchannel_self_healing_adaptation() -> None:
    """Test reverse backchannel directive triggering inline system adaptation and reasoning strip."""
    suite = TwoStageContextPipelineAndProviderProtocolDecouplingSuite(session_id="sess-pipe-003")

    directive = AssemblyAdjustmentDirective(
        requires_inline_system=True,
        strip_reasoning_traces=True,
        reason="Target proxy endpoint disallows separate system headers and reasoning tokens",
    )

    bundle = suite.assemble_logical_context(
        system_prompts=["CRITICAL: Inlined instructions"],
        manual_turns=[
            LogicalTurn(
                turn_id="t1",
                role="user",
                content="Please optimize query",
            ),
            LogicalTurn(
                turn_id="t2",
                role="assistant",
                content="Query optimized",
                reasoning_content="Hidden scratchpad that must be stripped",
            ),
        ],
        adjustment_directive=directive,
    )

    # System directives inlined into first user turn
    assert len(bundle.system_directives) == 0
    assert "CRITICAL: Inlined instructions" in bundle.dialogue_turns[0].content
    assert "Please optimize query" in bundle.dialogue_turns[0].content

    # Reasoning traces stripped
    assert bundle.dialogue_turns[1].reasoning_content is None


def test_end_to_end_pipeline_and_cryptographic_receipt() -> None:
    """Test full pipeline execution and cryptographic integrity receipt generation."""
    suite = TwoStageContextPipelineAndProviderProtocolDecouplingSuite(session_id="sess-pipe-004")

    payload, receipt, bundle = suite.run_end_to_end_pipeline(
        system_prompts=["System guidance"],
        target_provider=LlmProviderProtocolKind.ANTHROPIC,
        manual_turns=[
            LogicalTurn(turn_id="m1", role="user", content="Ping"),
            LogicalTurn(turn_id="m2", role="assistant", content="Pong"),
        ],
    )

    assert isinstance(payload, ProviderPayloadResult)
    assert isinstance(receipt, PipelineStageReceipt)
    assert receipt.session_id == "sess-pipe-004"
    assert receipt.target_provider == LlmProviderProtocolKind.ANTHROPIC
    assert receipt.turns_count == 2
    assert receipt.system_directives_count == 1
    assert receipt.wire_payload_bytes > 0
    assert len(receipt.pipeline_hash) == 16

    assert len(suite.get_stage_receipts()) == 1
