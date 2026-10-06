"""Unit tests for Pi Agent progressive compaction, cumulative file tracker,
and 30+ vendor context overflow detector.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.context_overflow_detector import (
    ContextOverflowDetector,
)
from myrm_agent_harness.runtime.context.pi_compaction_types import (
    CumulativeFileRecord,
    PiCompactionConfig,
)
from myrm_agent_harness.runtime.context.pi_progressive_compactor import (
    CumulativeFileTracker,
    PiProgressiveCompactor,
    find_protocol_safe_cut_point,
)
from myrm_agent_harness.runtime.context.surface_projection_types import (
    MessageRole,
    ProjectedMessage,
)


def test_protocol_safe_cut_point_never_splits_tool_result() -> None:
    """Verify cut point selection strictly avoids cutting at TOOL result messages."""
    messages = [
        ProjectedMessage(role=MessageRole.USER, content="Step 1: Check git branch"),
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Running git status",
            tool_calls=('{"name": "run_command", "arguments": {"cmd": "git status"}}',),
        ),
        ProjectedMessage(
            role=MessageRole.TOOL,
            content="On branch main, clean tree",
            tool_call_id="call-1",
            name="run_command",
        ),
        ProjectedMessage(role=MessageRole.USER, content="Step 2: Read config.yaml"),
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Reading config",
            tool_calls=('{"name": "read_file", "arguments": {"path": "config.yaml"}}',),
        ),
        ProjectedMessage(
            role=MessageRole.TOOL,
            content="version: 2.0\nenv: prod",
            tool_call_id="call-2",
            name="read_file",
        ),
        ProjectedMessage(role=MessageRole.USER, content="Step 3: What is the next task?"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="The next task is refactoring."),
    ]

    # Force a token budget that would naturally land near the TOOL result message
    cut = find_protocol_safe_cut_point(messages=messages, keep_recent_tokens=25)
    first_kept_msg = messages[cut.first_kept_index]

    # Must never be a TOOL message
    assert first_kept_msg.role != MessageRole.TOOL
    assert cut.first_kept_index in (3, 4, 6)


def test_cumulative_file_tracker_read_and_modified() -> None:
    """Verify CumulativeFileTracker extracts paths, merges cumulatively, and generates XML."""
    prev_record = CumulativeFileRecord(
        read_files=("legacy/old_spec.md",),
        modified_files=("legacy/old_code.py",),
    )

    new_messages = [
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Reading main.py",
            tool_calls=('{"name": "read_file", "arguments": {"path": "src/main.py"}}',),
        ),
        ProjectedMessage(
            role=MessageRole.TOOL,
            content="File contents of src/main.py...",
            name="read_file",
        ),
        ProjectedMessage(
            role=MessageRole.ASSISTANT,
            content="Updating config.json",
            tool_calls=('{"name": "write_to_file", "arguments": {"TargetFile": "src/config.json"}}',),
        ),
    ]

    updated_record = CumulativeFileTracker.extract_from_messages(
        messages=new_messages,
        prev_record=prev_record,
    )

    assert "legacy/old_spec.md" in updated_record.read_files
    assert "src/main.py" in updated_record.read_files
    assert "legacy/old_code.py" in updated_record.modified_files
    assert "src/config.json" in updated_record.modified_files

    xml_block = updated_record.render_xml_block()
    assert "<read-files>" in xml_block
    assert "<file>src/main.py</file>" in xml_block
    assert "<modified-files>" in xml_block
    assert "<file>src/config.json</file>" in xml_block


def test_context_overflow_detector_30_plus_vendors() -> None:
    """Verify ContextOverflowDetector catches vendor errors and excludes rate limits."""
    # Anthropic
    res_anthropic = ContextOverflowDetector.detect_error_overflow(
        "prompt is too long: 213462 tokens > 200000 maximum"
    )
    assert res_anthropic.is_overflow is True
    assert res_anthropic.vendor == "anthropic_token"

    # OpenAI
    res_openai = ContextOverflowDetector.detect_error_overflow(
        "Error: Your input exceeds the context window of this model."
    )
    assert res_openai.is_overflow is True
    assert res_openai.vendor == "openai_window"

    # Gemini
    res_gemini = ContextOverflowDetector.detect_error_overflow(
        "The input token count (1196265) exceeds the maximum number of tokens allowed (1048575)"
    )
    assert res_gemini.is_overflow is True
    assert res_gemini.vendor == "google_gemini"

    # llama.cpp
    res_llama = ContextOverflowDetector.detect_error_overflow(
        "the request exceeds the available context size, try increasing it"
    )
    assert res_llama.is_overflow is True
    assert res_llama.vendor == "llama_cpp"

    # Ollama explicit
    res_ollama = ContextOverflowDetector.detect_error_overflow(
        "prompt too long; exceeded max context length by 512 tokens"
    )
    assert res_ollama.is_overflow is True
    assert res_ollama.vendor == "ollama_explicit"

    # False positive rate limiting must NOT be detected as overflow
    res_rate_limit = ContextOverflowDetector.detect_error_overflow(
        "Throttling error: Too many tokens requested, please wait before retrying."
    )
    assert res_rate_limit.is_overflow is False
    assert res_rate_limit.vendor == "excluded_rate_limit"


def test_token_reconciliation_and_silent_truncation() -> None:
    """Verify reconciliation detects silent Ollama truncation and MiMo length stops."""
    # Ollama silent truncation: 8000 budgeted tokens but server only got 2048
    audit_ollama = ContextOverflowDetector.audit_token_reconciliation(
        prompt_budget_tokens=8000,
        server_received_tokens=2048,
        context_window=65536,
    )
    assert audit_ollama.is_overflow is True
    assert audit_ollama.is_silent_truncation is True
    assert audit_ollama.vendor == "ollama_silent_truncation"
    assert "PARAMETER num_ctx 65536" in audit_ollama.diagnostic_hint

    # Xiaomi MiMo length stop with output=0
    audit_mimo = ContextOverflowDetector.audit_token_reconciliation(
        prompt_budget_tokens=32000,
        server_received_tokens=32000,
        context_window=32000,
        stop_reason="length",
        output_tokens=0,
    )
    assert audit_mimo.is_overflow is True
    assert audit_mimo.is_silent_truncation is True
    assert audit_mimo.vendor == "xiaomi_mimo_truncation"


def test_pi_progressive_compactor_end_to_end() -> None:
    """Verify PiProgressiveCompactor end-to-end compaction and token shrinking."""
    messages = [
        ProjectedMessage(role=MessageRole.USER, content="Init project setup"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Project initialized successfully"),
        ProjectedMessage(role=MessageRole.USER, content="Implement authentication module"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Auth module implemented"),
        ProjectedMessage(role=MessageRole.USER, content="Write unit tests for authentication"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Unit tests written and passed"),
        ProjectedMessage(role=MessageRole.USER, content="Current status summary request"),
    ]

    config = PiCompactionConfig(
        context_window=1000,
        reserve_tokens=200,
        keep_recent_tokens=20,
        focus_directive="Focus on authentication test coverage",
    )

    res = PiProgressiveCompactor.compact(messages=messages, config=config)

    assert "<compaction_context>" in res.projected_messages[0].content
    assert "## Goal" in res.summary_text
    assert "## Additional Focus\nFocus on authentication test coverage" in res.summary_text
    assert len(res.projected_messages) < len(messages)
    assert res.tokens_before > 0


def test_branch_lca_summary_generation() -> None:
    """Verify generate_branch_lca_summary builds structured ancestor exploration context."""
    path = [
        ProjectedMessage(role=MessageRole.USER, content="Try experimental branch A"),
        ProjectedMessage(role=MessageRole.ASSISTANT, content="Compiled branch A successfully"),
    ]
    summary_msg = PiProgressiveCompactor.generate_branch_lca_summary(path, "branch-experiment-1")
    assert summary_msg.role == MessageRole.SYSTEM
    assert "<branch_lca_summary branch_id='branch-experiment-1'>" in summary_msg.content
    assert "Branch Exploration Summary" in summary_msg.content
