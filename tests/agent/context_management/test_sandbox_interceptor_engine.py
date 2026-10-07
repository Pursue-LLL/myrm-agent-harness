"""Tests for Sandbox Tool Output Interception and Local FTS5 Retrieval Suite (Item 232)."""

import pytest

from myrm_agent_harness.agent.context_management.sandbox_interceptor import (
    ContextHookStage,
    InterceptedToolOutput,
    LifecycleHookRecord,
    SandboxInterceptorConfig,
    SandboxOutputInterceptorEngine,
    SearchResultSnippet,
    ToolOutputStub,
)


def test_tool_output_interception_and_stubbing() -> None:
    """Verify small tool outputs pass through untouched, while bulky dumps get intercepted with 98% savings."""
    config = SandboxInterceptorConfig(interception_threshold_bytes=1000)
    engine = SandboxOutputInterceptorEngine(config)

    session_id = "sess-interception-test"

    # 1. Output below threshold: Pass-through
    short_text = "File successfully written to /workspace/src/app.py"
    out_pass, stub_pass = engine.intercept_tool_output("write_file", short_text, session_id)
    assert out_pass == short_text
    assert stub_pass is None

    # 2. Heavy output above threshold (e.g. 50KB Playwright DOM dump)
    bulky_line = "<tr><td>User record row</td><td>active</td><td>2026-10-08</td></tr>\n"
    bulky_text = (
        "<!DOCTYPE html><html><body>\n"
        + (bulky_line * 800)
        + "<div id='footer'>Copyright 2026 Myrm AI</div></body></html>"
    )
    raw_bytes = len(bulky_text.encode("utf-8"))
    assert raw_bytes > 40000

    stub_text, stub = engine.intercept_tool_output("browser_snapshot", bulky_text, session_id)
    assert stub is not None
    assert stub.tool_name == "browser_snapshot"
    assert stub.raw_size_bytes == raw_bytes
    assert stub.line_count > 800
    assert stub.tokens_saved > 9000

    # Ensure stub text is compact (< 500 chars)
    assert len(stub_text) < 500
    assert "Tool Output Intercepted: 'browser_snapshot'" in stub_text
    assert stub.content_id in stub_text
    assert "ctx_search" in stub_text

    engine.close()


def test_local_sqlite_fts5_exact_search() -> None:
    """Verify ctx_search accurately returns verbatim lines with exact line numbers from local SQLite."""
    config = SandboxInterceptorConfig(interception_threshold_bytes=500)
    engine = SandboxOutputInterceptorEngine(config)

    session_id = "sess-search-test"

    git_log_output = (
        "commit a1b2c3d4 (HEAD -> main)\n"
        "Author: Architect <dev@myrm.ai>\n"
        "Date:   Wed Oct 8 2026\n"
        "\n"
        "    feat: add distributed lock manager\n"
        "\n"
        "commit e5f6a7b8\n"
        "Author: Engineer <eng@myrm.ai>\n"
        "Date:   Tue Oct 7 2026\n"
        "\n"
        "    fix: resolve CRITICAL_PAYMENT_GATEWAY_TIMEOUT bug in checkout worker\n"
        "\n"
        + ("commit filler\n" * 50)
    )

    stub_text, stub = engine.intercept_tool_output("git_log", git_log_output, session_id)
    assert stub is not None

    # Search for specific error token inside intercepted content
    results = engine.ctx_search(
        query="CRITICAL_PAYMENT_GATEWAY_TIMEOUT",
        content_id=stub.content_id,
        limit=3,
    )

    assert len(results) >= 1
    hit = results[0]
    assert hit.content_id == stub.content_id
    assert "CRITICAL_PAYMENT_GATEWAY_TIMEOUT" in hit.snippet
    assert hit.line_number == 11
    assert hit.match_score == 1.0

    # Search non-existent token
    empty_results = engine.ctx_search(
        query="NON_EXISTENT_TOKEN_XYZ",
        content_id=stub.content_id,
    )
    assert len(empty_results) == 0

    engine.close()


def test_five_stage_context_lifecycle_hooks() -> None:
    """Verify five-stage Context Mode lifecycle hooks record sequential snapshots for lossless resumption."""
    engine = SandboxOutputInterceptorEngine(SandboxInterceptorConfig())
    session_id = "sess-lifecycle-stage-flow"

    # Stage 1: Pre-tool use
    rec_pre_tool = engine.trigger_hook(
        stage=ContextHookStage.PRE_TOOL_USE,
        session_id=session_id,
        payload={"tool": "run_command", "args": "git diff --stat"},
    )
    assert rec_pre_tool.stage == ContextHookStage.PRE_TOOL_USE
    assert len(rec_pre_tool.payload_digest) == 16

    # Stage 2: Post-tool use
    rec_post_tool = engine.trigger_hook(
        stage=ContextHookStage.POST_TOOL_USE,
        session_id=session_id,
        payload={"tool": "run_command", "status": "success", "lines": "12"},
    )
    assert rec_post_tool.stage == ContextHookStage.POST_TOOL_USE

    # Stage 3: User prompt submit
    rec_user = engine.trigger_hook(
        stage=ContextHookStage.USER_PROMPT_SUBMIT,
        session_id=session_id,
        payload={"prompt": "Please optimize memory consumption now"},
    )
    assert rec_user.stage == ContextHookStage.USER_PROMPT_SUBMIT

    # Stage 4: Pre-compaction freeze
    rec_pre_compact = engine.trigger_hook(
        stage=ContextHookStage.PRE_COMPACT,
        session_id=session_id,
        payload={"turn": "15", "current_tokens": "95000", "preserved_keys": "todos,genesis"},
    )
    assert rec_pre_compact.stage == ContextHookStage.PRE_COMPACT

    # Stage 5: Session resume
    rec_resume = engine.trigger_hook(
        stage=ContextHookStage.SESSION_RESUME,
        session_id=session_id,
        payload={"checkpoint_id": "chk-0099", "restored_turn": "16"},
    )
    assert rec_resume.stage == ContextHookStage.SESSION_RESUME

    # Verify chronological sequence
    history = engine.get_lifecycle_history(session_id)
    assert len(history) == 5
    assert [h.stage for h in history] == [
        ContextHookStage.PRE_TOOL_USE,
        ContextHookStage.POST_TOOL_USE,
        ContextHookStage.USER_PROMPT_SUBMIT,
        ContextHookStage.PRE_COMPACT,
        ContextHookStage.SESSION_RESUME,
    ]

    engine.close()
