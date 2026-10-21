"""Tests for Exact Identifier Anchor Indexing Engine.

Validates deterministic extraction of commit SHAs, file paths, high severity errors,
code symbols, and API endpoints without hallucination or LLM overhead.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.summary.exact_anchor import (
    ExactAnchorFilterConfig,
    ExactAnchorTable,
    extract_exact_anchors,
)


def test_exact_anchor_table_properties_and_immutability() -> None:
    """Validate empty state, total count, and immutability of ExactAnchorTable."""
    empty_table = ExactAnchorTable()
    assert empty_table.is_empty is True
    assert empty_table.total_count == 0
    assert empty_table.format_markdown() == ""

    filled_table = ExactAnchorTable(
        commit_shas=("a1b2c3d4e5f67890123456789012345678901234",),
        file_paths=("src/core/engine.py",),
        error_spans=("SyntaxError: invalid syntax",),
        code_symbols=("CompactEngine",),
        api_endpoints=("/api/v1/sessions/compact",),
    )
    assert filled_table.is_empty is False
    assert filled_table.total_count == 5

    # Immutability check
    with pytest.raises(AttributeError):
        # pyright: ignore[reportAttributeAccessIssue]
        filled_table.commit_shas = ()  # type: ignore[misc]

    md = filled_table.format_markdown()
    assert "### ⚓ Exact Anchor Index (Machine-Extracted Truth)" in md
    assert "- **Error Signatures**:" in md
    assert "<!-- EXACT_ANCHOR_JSON:" in md
    assert "`a1b2c3d4e5f67890123456789012345678901234`" in md
    assert "`src/core/engine.py`" in md
    assert "`CompactEngine`" in md
    assert "`/api/v1/sessions/compact`" in md
    assert "SyntaxError: invalid syntax" in md

    dict_repr = filled_table.to_dict()
    assert dict_repr["commit_shas"] == ["a1b2c3d4e5f67890123456789012345678901234"]
    assert dict_repr["file_paths"] == ["src/core/engine.py"]


def test_extract_commit_shas_and_file_paths() -> None:
    """Ensure git commit SHAs (40 hex and prefixed 7+ hex) and file paths are extracted."""
    messages = [
        HumanMessage(content="Please review commit 7a8b9c0 in src/app/main.py and config.yaml"),
        AIMessage(content="Commit 1234567890abcdef1234567890abcdef12345678 modified packages/core/index.ts"),
    ]

    table = extract_exact_anchors(messages)

    assert "7a8b9c0" in table.commit_shas
    assert "1234567890abcdef1234567890abcdef12345678" in table.commit_shas
    assert "src/app/main.py" in table.file_paths
    assert "config.yaml" in table.file_paths
    assert "packages/core/index.ts" in table.file_paths


def test_extract_code_symbols_and_noise_filtering() -> None:
    """Ensure functions and classes are indexed while common keywords/noise are ignored."""
    messages = [
        HumanMessage(content="We need to implement class ExactAnchorIndex and def summarize_turns()"),
        ToolMessage(content="function handle_compaction() and let temp_val = 1", tool_call_id="call_1"),
        AIMessage(content="def print(): pass  # noise word should be skipped"),
    ]

    table = extract_exact_anchors(messages)

    assert "ExactAnchorIndex" in table.code_symbols
    assert "summarize_turns" in table.code_symbols
    assert "handle_compaction" in table.code_symbols
    # print is a noise word and must be filtered out
    assert "print" not in [s.lower() for s in table.code_symbols]


def test_extract_high_severity_errors_and_api_endpoints() -> None:
    """Verify tracebacks and fatal errors are captured and endpoints parsed."""
    messages = [
        ToolMessage(
            content=(
                "Failed request to /api/v1/auth/tokens\n"
                "Traceback (most recent call last):\n"
                "  File 'run.py', line 10\n"
                "ModuleNotFoundError: No module named 'foo'"
            ),
            tool_call_id="call_err",
        )
    ]

    table = extract_exact_anchors(messages)

    assert "/api/v1/auth/tokens" in table.api_endpoints
    assert any("Traceback" in err or "ModuleNotFoundError" in err for err in table.error_spans)


def test_quota_limits_and_safety_boundaries() -> None:
    """Test quota enforcement and line length protection."""
    cfg = ExactAnchorFilterConfig(
        max_commit_shas=2,
        max_file_paths=2,
        max_line_length=50,
        max_scan_total_chars=200,
    )

    long_line = "a" * 100 + " src/long/path/skipped.py"
    messages = [
        HumanMessage(content=long_line),
        AIMessage(
            content="commit 1111111 commit 2222222 commit 3333333 in file1.py and file2.py and file3.py"
        ),
    ]

    table = extract_exact_anchors(messages, config=cfg)

    # Shas and paths capped at 2
    assert len(table.commit_shas) <= 2
    assert len(table.file_paths) <= 2
    # Long line truncated before 'src/long/path/skipped.py'
    assert "src/long/path/skipped.py" not in table.file_paths


def test_recency_first_extraction_favors_recent_messages() -> None:
    """Ensure recent turns are prioritized over early turns when capacity is capped."""
    cfg = ExactAnchorFilterConfig(max_file_paths=2)

    messages = [
        HumanMessage(content="Early turn: modified old_file_1.py and old_file_2.py"),
        AIMessage(content="Later turn: touched recent_critical_file.py"),
    ]

    table = extract_exact_anchors(messages, config=cfg)

    # recent_critical_file.py MUST be captured because of reverse-order scanning
    assert "recent_critical_file.py" in table.file_paths
    assert len(table.file_paths) == 2


def test_dependency_and_build_path_blacklist() -> None:
    """Ensure node_modules, .venv, .git, and build artifacts are stripped."""
    messages = [
        ToolMessage(
            content=(
                "Failure at node_modules/vitest/dist/index.js line 4\n"
                "Also checked .venv/lib/python3.11/site-packages/pkg.py\n"
                "Real user file: src/services/user_service.py"
            ),
            tool_call_id="call_noise",
        )
    ]

    table = extract_exact_anchors(messages)

    assert "src/services/user_service.py" in table.file_paths
    assert not any("node_modules" in p for p in table.file_paths)
    assert not any(".venv" in p for p in table.file_paths)

