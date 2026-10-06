"""Tests for runtime tool output token auditor and dynamic semantic truncation engine."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.tool_output_auditor import (
    DynamicSemanticTruncationConfig,
    DynamicSemanticTruncator,
    ToolOutputTokenAuditor,
)


def test_within_budget_passthrough() -> None:
    """Outputs within token and char limits must pass through untouched."""
    auditor = ToolOutputTokenAuditor(
        DynamicSemanticTruncationConfig(max_tokens_budget=500, max_chars_budget=2000)
    )
    raw_output = "Line 1: system ok\nLine 2: job complete\n"

    processed, record = auditor.audit_and_truncate(
        tool_name="bash",
        output=raw_output,
        call_id="call_001",
    )

    assert processed == raw_output
    assert not record.is_truncated
    assert record.saved_tokens == 0
    assert record.omitted_lines == 0
    assert record.preserved_patterns == []
    assert record.original_chars == len(raw_output)


def test_single_line_massive_payload_truncation() -> None:
    """Low line-count inputs with massive characters trigger boundary-safe compression."""
    truncator = DynamicSemanticTruncator(
        DynamicSemanticTruncationConfig(
            max_tokens_budget=100,
            max_chars_budget=300,
            head_lines=5,
            tail_lines=5,
        )
    )
    massive_blob = "A" * 5000 + "\n" + "B" * 5000

    processed, is_truncated, _omitted, patterns = truncator.truncate(massive_blob)

    assert is_truncated
    assert "因单行超限已执行 Token 边界紧缩截断" in processed
    assert "token_boundary_fallback" in patterns
    assert len(processed) < len(massive_blob)


def test_semantic_truncation_preserves_head_tail_and_errors() -> None:
    """Multi-line outputs fold filler logs while preserving head, tail, and error traces."""
    config = DynamicSemanticTruncationConfig(
        max_tokens_budget=150,
        max_chars_budget=800,
        head_lines=3,
        tail_lines=3,
        max_middle_pattern_lines=5,
    )
    auditor = ToolOutputTokenAuditor(config)

    lines: list[str] = [f"START_HEADER_{i}" for i in range(1, 4)]
    # Middle filler logs
    for i in range(1, 40):
        lines.append(f"debug log stream item {i}: running worker loop")
    # Injected critical errors and search match
    lines.append("Traceback (most recent call last): NullPointerException in worker")
    lines.append("matches found 42 entries")
    lines.append("CRITICAL: connection terminated by foreign host")
    for i in range(41, 70):
        lines.append(f"debug log stream item {i}: running worker loop")
    lines.extend([f"FINISH_TAIL_{i}" for i in range(1, 4)])

    raw_output = "\n".join(lines)

    processed, record = auditor.audit_and_truncate(
        tool_name="grep_logs",
        output=raw_output,
        call_id="call_002",
    )

    assert record.is_truncated
    assert record.saved_tokens > 0
    assert record.omitted_lines > 50
    assert "error_trace" in record.preserved_patterns
    assert "keyword_match" in record.preserved_patterns

    # Check preserved components
    assert "START_HEADER_1" in processed
    assert "FINISH_TAIL_3" in processed
    assert "NullPointerException" in processed
    assert "matches found" in processed
    assert "已动态语义折叠" in processed


def test_auditor_aggregation_and_top_hungry_tools() -> None:
    """Auditor correctly aggregates per-tool metrics and sorts hungry tools."""
    config = DynamicSemanticTruncationConfig(max_tokens_budget=80, max_chars_budget=400)
    auditor = ToolOutputTokenAuditor(config)

    # 1. Short call for ping
    auditor.audit_and_truncate("ping", "pong ok\n")

    # 2. Heavy calls for bash
    heavy_bash = "\n".join([f"bash log entry {i}" for i in range(100)])
    auditor.audit_and_truncate("bash", heavy_bash, call_id="c_b1")
    auditor.audit_and_truncate("bash", heavy_bash, call_id="c_b2")

    # 3. Moderate call for file_read
    mod_file = "\n".join([f"file content line {i}" for i in range(40)])
    auditor.audit_and_truncate("file_read", mod_file, call_id="c_f1")

    summary = auditor.get_summary()

    assert summary.total_calls == 4
    assert summary.truncated_calls >= 3
    assert summary.total_saved_tokens > 0
    assert 0.0 < summary.overall_savings_ratio <= 1.0

    # Top hungry ranking
    top_tools = summary.top_hungry_tools(k=2)
    assert len(top_tools) == 2
    assert top_tools[0][0] == "bash"

    bash_stats = summary.tool_stats["bash"]
    assert bash_stats.call_count == 2
    assert bash_stats.truncation_count == 2
    assert bash_stats.truncation_rate == 1.0
    assert bash_stats.savings_ratio > 0.40

    # Reset behavior
    auditor.reset()
    clean_summary = auditor.get_summary()
    assert clean_summary.total_calls == 0
    assert clean_summary.total_original_tokens == 0
    assert len(clean_summary.tool_stats) == 0


def test_extreme_output_hard_budget_guard() -> None:
    """Extremely massive outputs are strictly guaranteed not to exceed max token budget."""
    config = DynamicSemanticTruncationConfig(
        max_tokens_budget=120,
        max_chars_budget=500,
        head_lines=5,
        tail_lines=5,
    )
    truncator = DynamicSemanticTruncator(config)

    # 500 lines of error traces
    lines = [f"CRITICAL: error event number {i} happened" for i in range(500)]
    raw_output = "\n".join(lines)

    processed, is_truncated, _omitted, _patterns = truncator.truncate(raw_output)

    assert is_truncated
    from myrm_agent_harness.utils.text_utils import get_token_count

    token_count = get_token_count(processed)
    assert token_count <= config.max_tokens_budget
