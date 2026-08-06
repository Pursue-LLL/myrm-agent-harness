"""Tests for MCP batch-read next-step hint appended to file_read_tool output."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_ops.mcp_read_next_step_hint import (
    append_mcp_docs_next_step_hint,
    is_mcp_function_doc_batch,
)


def test_is_mcp_function_doc_batch_all_mcp() -> None:
    paths = [
        "/mcp/demo_skill/get_foo.md",
        "/mcp/demo_skill/get_bar.md",
    ]
    assert is_mcp_function_doc_batch(paths) is True


def test_is_mcp_function_doc_batch_mixed_paths() -> None:
    assert is_mcp_function_doc_batch(["/mcp/s/a.md", "/workspace/x.py"]) is False
    assert is_mcp_function_doc_batch(["/workspace/readme.md"]) is False
    assert is_mcp_function_doc_batch([]) is False


def test_append_hint_only_for_mcp_batch() -> None:
    body = "=== doc ===\nparams: x"
    mcp_paths = ["/mcp/skill/a.md", "/mcp/skill/b.md"]
    hinted = append_mcp_docs_next_step_hint(body, mcp_paths)
    assert "[MCP NEXT STEP]" in hinted
    assert "one" in hinted.lower()
    assert "[RESULT]" in hinted
    assert append_mcp_docs_next_step_hint(body, ["/workspace/a.py"]) == body


def test_append_hint_idempotent() -> None:
    paths = ["/mcp/s/a.md"]
    once = append_mcp_docs_next_step_hint("doc", paths)
    twice = append_mcp_docs_next_step_hint(once, paths)
    assert twice.count("[MCP NEXT STEP]") == 1
