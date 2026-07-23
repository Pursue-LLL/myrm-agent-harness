"""Real integration tests for ACP module with live CLI backends.

These tests spawn actual CLI processes (Claude Code, Codex, Gemini)
and verify end-to-end event parsing, session management, and pool routing.

Requirements:
- claude, codex, gemini CLIs installed and in PATH
- Valid API keys configured in environment
- Network access for LLM API calls

Mark: @pytest.mark.integration — skipped unless --run-integration flag is passed.
"""

from __future__ import annotations

import os
import shutil

import pytest

from myrm_agent_harness.toolkits.acp.acp_agent_tools import create_delegate_to_agent_tool
from myrm_agent_harness.toolkits.acp.backend_detector import BackendDetector
from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import CliRuntime
from myrm_agent_harness.toolkits.acp.runtime.pool import RuntimePool
from myrm_agent_harness.toolkits.acp.types import (
    RuntimeConfig,
    RuntimeEventType,
)

SIMPLE_PROMPT = (
    "Reply ONLY with the exact text 'PONG' and nothing else. "
    "Do not add any explanation, formatting, or extra characters."
)

TIMEOUT = 120


def _has_cli(name: str) -> bool:
    return shutil.which(name) is not None


_HAS_CLAUDE = _has_cli("claude")
_HAS_CODEX = _has_cli("codex")
_HAS_GEMINI = _has_cli("gemini")

skip_no_claude = pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not installed")
skip_no_codex = pytest.mark.skipif(not _HAS_CODEX, reason="codex CLI not installed")
skip_no_gemini = pytest.mark.skipif(not _HAS_GEMINI, reason="gemini CLI not installed")

pytestmark = pytest.mark.integration


# ── BackendDetector ─────────────────────────────────────────────────────


class TestBackendDetectorReal:
    """Live detection of installed CLI backends."""

    @pytest.mark.asyncio
    async def test_detect_finds_installed_backends(self) -> None:
        detector = BackendDetector()
        results = await detector.detect(include_version=True)

        found_names = {r.name for r in results}

        if _HAS_CLAUDE:
            assert "claude" in found_names
        if _HAS_CODEX:
            assert "codex" in found_names
        if _HAS_GEMINI:
            assert "gemini" in found_names

        for r in results:
            assert r.path
            assert os.path.isfile(r.path)

    @pytest.mark.asyncio
    async def test_detect_extracts_versions(self) -> None:
        detector = BackendDetector()
        results = await detector.detect(include_version=True)

        for r in results:
            assert r.version is not None, f"{r.name} version should not be None"
            assert len(r.version) > 0, f"{r.name} version should not be empty"

    @pytest.mark.asyncio
    async def test_cache_and_invalidate(self) -> None:
        detector = BackendDetector()
        first = await detector.detect(include_version=False)
        second = await detector.detect(include_version=False)
        assert first is second

        detector.invalidate_cache()
        third = await detector.detect(include_version=False)
        assert third is not first
        assert len(third) == len(first)


# ── Claude CLI ──────────────────────────────────────────────────────────


@skip_no_claude
class TestClaudeCliReal:
    """Live tests against Claude Code CLI."""

    def _make_config(self, **overrides: object) -> RuntimeConfig:
        defaults: dict[str, object] = {
            "backend_type": "cli",
            "command": "claude",
            "args": ["--output-format", "stream-json", "-p"],
            "timeout_seconds": TIMEOUT,
            "max_turns": 1,
        }
        defaults.update(overrides)
        return RuntimeConfig(**defaults)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_basic_prompt_returns_text(self) -> None:
        rt = CliRuntime("claude-test", self._make_config())
        events: list[object] = []

        async for event in rt.run_turn(SIMPLE_PROMPT, "claude-real-s1"):
            events.append(event)

        types = [e.type for e in events]
        assert RuntimeEventType.TEXT_DELTA in types, f"Expected TEXT_DELTA, got: {types}"
        assert RuntimeEventType.DONE in types, f"Expected DONE, got: {types}"

        text = "".join(
            e.data["content"]
            for e in events
            if e.type == RuntimeEventType.TEXT_DELTA and isinstance(e.data.get("content"), str)
        )
        assert len(text) > 0, "Should receive non-empty text response"

    @pytest.mark.asyncio
    async def test_usage_events_present(self) -> None:
        rt = CliRuntime("claude-usage", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "claude-usage-s1")]

        usage_events = [e for e in events if e.type == RuntimeEventType.USAGE_UPDATE]
        assert len(usage_events) > 0, "Claude should emit usage events"

        for ue in usage_events:
            assert "input_tokens" in ue.data
            assert "output_tokens" in ue.data

    @pytest.mark.asyncio
    async def test_status_update_at_start(self) -> None:
        rt = CliRuntime("claude-status", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "claude-status-s1")]

        status_events = [e for e in events if e.type == RuntimeEventType.STATUS_UPDATE]
        assert len(status_events) > 0, "Should emit STATUS_UPDATE at start"
        assert status_events[0].data["status"] == "starting"


# ── Codex CLI ───────────────────────────────────────────────────────────


@skip_no_codex
class TestCodexCliReal:
    """Live tests against Codex CLI.

    Codex uses ``exec --json --full-auto`` for non-interactive NDJSON output.
    The prompt is passed via stdin (``-p`` flag triggers stdin mode).
    """

    def _make_config(self, **overrides: object) -> RuntimeConfig:
        defaults: dict[str, object] = {
            "backend_type": "cli",
            "command": "codex",
            "args": ["exec", "--json", "--full-auto", "-p"],
            "timeout_seconds": TIMEOUT,
            "max_turns": 1,
        }
        defaults.update(overrides)
        return RuntimeConfig(**defaults)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_basic_prompt_produces_events(self) -> None:
        """Codex should produce parseable NDJSON events.

        With valid API quota: TEXT_DELTA + DONE.
        With exhausted quota: ERROR (rate_limited / turn.failed) — still validates parsing.
        """
        rt = CliRuntime("codex-test", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "codex-real-s1")]

        types = [e.type for e in events]
        assert len(types) > 0, "Codex should produce at least one event"
        assert RuntimeEventType.STATUS_UPDATE in types, "Should emit STATUS_UPDATE at start"

        has_text = RuntimeEventType.TEXT_DELTA in types
        has_error = RuntimeEventType.ERROR in types
        has_done = RuntimeEventType.DONE in types
        assert has_text or has_error or has_done, f"Expected TEXT_DELTA, ERROR, or DONE, got: {types}"

    @pytest.mark.asyncio
    async def test_codex_ndjson_parsing(self) -> None:
        """Verify NDJSON event stream is parseable regardless of API quota."""
        rt = CliRuntime("codex-parse", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "codex-parse-s1")]

        for event in events:
            assert event.type in RuntimeEventType.__members__.values()
            assert event.session_id == "codex-parse-s1"
            assert isinstance(event.data, dict)


# ── Gemini CLI ──────────────────────────────────────────────────────────


@skip_no_gemini
class TestGeminiCliReal:
    """Live tests against Gemini CLI.

    Gemini uses ``--output-format stream-json`` for NDJSON output.
    The prompt is passed via ``-p <prompt>`` (prompt as argument, not stdin).
    Note: ``-p`` in Gemini requires the prompt value immediately after the flag.
    """

    def _make_config(self, **overrides: object) -> RuntimeConfig:
        """Gemini config: prompt is appended as trailing argument (no -p flag).

        Gemini CLI's ``-p/--prompt`` expects a value argument immediately after
        the flag (``-p "my prompt"``), not stdin input. To avoid confusion with
        the stdin-based ``-p`` detection in CliRuntime, we omit ``-p`` and let
        CliRuntime append the prompt as a trailing positional argument.
        """
        defaults: dict[str, object] = {
            "backend_type": "cli",
            "command": "gemini",
            "args": ["--output-format", "stream-json", "--yolo"],
            "timeout_seconds": TIMEOUT,
            "max_turns": 1,
        }
        defaults.update(overrides)
        return RuntimeConfig(**defaults)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_basic_prompt_produces_events(self) -> None:
        """Gemini should produce parseable events.

        With valid auth/network: TEXT_DELTA + DONE.
        With network/auth issues: ERROR — still validates runtime lifecycle.
        """
        rt = CliRuntime("gemini-test", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "gemini-real-s1")]

        types = [e.type for e in events]
        assert len(types) > 0, "Gemini should produce at least one event"
        assert RuntimeEventType.STATUS_UPDATE in types, "Should emit STATUS_UPDATE at start"

        has_text = RuntimeEventType.TEXT_DELTA in types
        has_error = RuntimeEventType.ERROR in types
        has_done = RuntimeEventType.DONE in types
        assert has_text or has_error or has_done, f"Expected TEXT_DELTA, ERROR, or DONE, got: {types}"

    @pytest.mark.asyncio
    async def test_gemini_event_validation(self) -> None:
        """Verify all events have correct structure regardless of API status."""
        rt = CliRuntime("gemini-validate", self._make_config())
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, "gemini-validate-s1")]

        for event in events:
            assert event.type in RuntimeEventType.__members__.values()
            assert event.session_id == "gemini-validate-s1"
            assert isinstance(event.data, dict)


# ── RuntimePool ─────────────────────────────────────────────────────────


class TestRuntimePoolReal:
    """End-to-end tests with RuntimePool managing real backends."""

    def _build_pool(self) -> RuntimePool:
        pool = RuntimePool(max_concurrent=2)

        if _HAS_CLAUDE:
            pool.register(
                "claude",
                RuntimeConfig(
                    backend_type="cli",
                    command="claude",
                    args=["--output-format", "stream-json", "-p"],
                    timeout_seconds=TIMEOUT,
                    max_turns=1,
                    description="Claude Code CLI",
                ),
            )
        if _HAS_CODEX:
            pool.register(
                "codex",
                RuntimeConfig(
                    backend_type="cli",
                    command="codex",
                    args=["exec", "--json", "--full-auto", "-p"],
                    timeout_seconds=TIMEOUT,
                    max_turns=1,
                    description="Codex CLI",
                ),
            )
        if _HAS_GEMINI:
            pool.register(
                "gemini",
                RuntimeConfig(
                    backend_type="cli",
                    command="gemini",
                    args=["--output-format", "stream-json", "--yolo"],
                    timeout_seconds=TIMEOUT,
                    max_turns=1,
                    description="Gemini CLI",
                ),
            )
        return pool

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not (_HAS_CLAUDE or _HAS_CODEX or _HAS_GEMINI),
        reason="At least one CLI backend required",
    )
    async def test_pool_prompt_completes(self) -> None:
        """Pool.prompt should complete without exception.

        The response may be empty if the backend times out or has API issues,
        but pool.prompt itself should handle these gracefully.
        """
        pool = self._build_pool()
        try:
            backend_name = pool.available_backends[0]
            response = await pool.prompt(backend_name, SIMPLE_PROMPT, mode="oneshot")
            assert isinstance(response, str), f"Pool.prompt to {backend_name} should return str"
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not (_HAS_CLAUDE or _HAS_CODEX or _HAS_GEMINI),
        reason="At least one CLI backend required",
    )
    async def test_pool_run_turn_streams_events(self) -> None:
        pool = self._build_pool()
        try:
            backend_name = pool.available_backends[0]
            session_id = f"{backend_name}-pool-stream"
            events = [
                e async for e in pool.run_turn(backend_name, SIMPLE_PROMPT, session_id=session_id, mode="oneshot")
            ]
            types = {e.type for e in events}
            assert len(types) > 0, "Pool should produce at least one event"
            assert RuntimeEventType.STATUS_UPDATE in types
            has_text = RuntimeEventType.TEXT_DELTA in types
            has_done = RuntimeEventType.DONE in types
            has_error = RuntimeEventType.ERROR in types
            assert has_text or has_done or has_error, f"Expected TEXT_DELTA, DONE, or ERROR, got: {types}"
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not (_HAS_CLAUDE and _HAS_GEMINI),
        reason="Need both Claude and Gemini for multi-backend test",
    )
    async def test_pool_multi_backend_sequential(self) -> None:
        """Test sequential prompts to different backends via the same pool.

        Each backend is called in oneshot mode. We verify that the pool
        correctly routes to different backends and handles their responses.
        An empty response from one backend (e.g. Gemini with network issues)
        is acceptable — the key verification is that pool routing works.
        """
        pool = self._build_pool()
        try:
            r1 = await pool.prompt("claude", SIMPLE_PROMPT, mode="oneshot")
            r2 = await pool.prompt("gemini", SIMPLE_PROMPT, mode="oneshot")
            assert len(r1) > 0, "Claude should return non-empty response"
            # Gemini may return empty due to network/auth — verify no exception raised
            assert isinstance(r2, str), "Gemini should return a string (may be empty on network error)"
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not (_HAS_CLAUDE or _HAS_CODEX or _HAS_GEMINI),
        reason="At least one CLI backend required",
    )
    async def test_pool_unknown_backend_raises(self) -> None:
        pool = self._build_pool()
        try:
            with pytest.raises(KeyError, match="Unknown backend"):
                await pool.prompt("nonexistent-agent", SIMPLE_PROMPT)
        finally:
            await pool.close_all()


# ── delegate_to_agent tool ──────────────────────────────────────────────


class TestDelegateToolReal:
    """End-to-end tests for the delegate_to_agent LangChain tool."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not installed")
    async def test_delegate_to_claude(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "claude",
            RuntimeConfig(
                backend_type="cli",
                command="claude",
                args=["--output-format", "stream-json", "-p"],
                timeout_seconds=TIMEOUT,
                max_turns=1,
                description="Claude Code CLI",
            ),
        )

        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        try:
            result = await tool_func.ainvoke({"agent_name": "claude", "task": SIMPLE_PROMPT, "mode": "oneshot"})
            assert isinstance(result, str)
            assert len(result) > 0
            # Claude may return delegation result or error (e.g. timeout, rate limit)
            assert "[Delegation:" in result or "[error]" in result
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _HAS_GEMINI, reason="gemini CLI not installed")
    async def test_delegate_to_gemini(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "gemini",
            RuntimeConfig(
                backend_type="cli",
                command="gemini",
                args=["--output-format", "stream-json", "--yolo"],
                timeout_seconds=TIMEOUT,
                max_turns=1,
                description="Gemini CLI",
            ),
        )

        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        try:
            result = await tool_func.ainvoke({"agent_name": "gemini", "task": SIMPLE_PROMPT, "mode": "oneshot"})
            assert isinstance(result, str)
            assert len(result) > 0
            # Gemini may return delegation result or error (e.g. network/auth issues)
            assert "[Delegation:" in result or "[error]" in result
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _HAS_CODEX, reason="codex CLI not installed")
    async def test_delegate_to_codex(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "codex",
            RuntimeConfig(
                backend_type="cli",
                command="codex",
                args=["exec", "--json", "--full-auto", "-p"],
                timeout_seconds=TIMEOUT,
                max_turns=1,
                description="Codex CLI",
            ),
        )

        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        try:
            result = await tool_func.ainvoke({"agent_name": "codex", "task": SIMPLE_PROMPT, "mode": "oneshot"})
            assert isinstance(result, str)
            assert len(result) > 0
            # Codex may return delegation result or error (e.g. quota exhausted)
            assert "[Delegation:" in result or "[error]" in result
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_delegate_to_unknown_agent(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        result = await tool_func.ainvoke({"agent_name": "nonexistent", "task": "hello", "mode": "oneshot"})
        assert "Unknown backend" in result

    @pytest.mark.asyncio
    async def test_delegate_invalid_mode(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "dummy",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        result = await tool_func.ainvoke({"agent_name": "dummy", "task": "hello", "mode": "bad_mode"})
        assert "[error]" in result
        assert "Invalid mode" in result

    @pytest.mark.asyncio
    async def test_delegate_task_too_large(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "dummy",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        tool_func = create_delegate_to_agent_tool(pool, cwd=os.getcwd())
        huge_task = "x" * (3 * 1024 * 1024)
        result = await tool_func.ainvoke({"agent_name": "dummy", "task": huge_task, "mode": "oneshot"})
        assert "[error]" in result
        assert "too large" in result.lower()


# ── Edge Cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case and boundary tests for robustness."""

    @pytest.mark.asyncio
    async def test_cli_runtime_nonexistent_command(self) -> None:
        """CliRuntime with a non-existent command should emit ERROR."""
        rt = CliRuntime(
            "fake",
            RuntimeConfig(backend_type="cli", command="/nonexistent/agent"),
        )
        events = [e async for e in rt.run_turn("hello", "edge-s1")]
        types = [e.type for e in events]
        assert RuntimeEventType.ERROR in types

    @pytest.mark.asyncio
    async def test_cli_runtime_empty_prompt(self) -> None:
        """CliRuntime should handle empty prompt without crashing."""
        if not _HAS_CLAUDE:
            pytest.skip("claude CLI not installed")
        rt = CliRuntime(
            "claude-empty",
            RuntimeConfig(
                backend_type="cli",
                command="claude",
                args=["--output-format", "stream-json", "-p"],
                timeout_seconds=30,
                max_turns=1,
            ),
        )
        events = [e async for e in rt.run_turn("", "edge-empty-s1")]
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_pool_close_all_idempotent(self) -> None:
        """Calling close_all multiple times should not raise."""
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "dummy",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        await pool.close_all()
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_pool_cancel_nonexistent_backend(self) -> None:
        """Cancelling a non-instantiated backend should be a no-op."""
        pool = RuntimePool(max_concurrent=2)
        pool.register(
            "dummy",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        await pool.cancel("dummy", "any-session")

    @pytest.mark.asyncio
    async def test_backend_detector_cache_shared_across_instances(self) -> None:
        """Different BackendDetector instances should share process-wide cache."""
        BackendDetector.invalidate_shared_cache()
        d1 = BackendDetector()
        d2 = BackendDetector()
        r1 = await d1.detect(include_version=False)
        r2 = await d2.detect(include_version=False)
        assert r1 is r2
        assert len(r1) == len(r2)

    @pytest.mark.asyncio
    async def test_cli_runtime_cancel_no_process(self) -> None:
        """Cancelling before any run_turn should be a no-op."""
        rt = CliRuntime(
            "cancel-test",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        await rt.cancel("any-session")

    @pytest.mark.asyncio
    async def test_cli_runtime_close_clears_state(self) -> None:
        """Closing a CliRuntime should clear all internal state."""
        rt = CliRuntime(
            "close-test",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        await rt.close()
        assert rt.is_alive is False
        assert rt._process is None

    @pytest.mark.asyncio
    async def test_pool_health_metrics_empty(self) -> None:
        """Health metrics should be empty when monitor is disabled."""
        pool = RuntimePool(max_concurrent=2, enable_health_monitor=False)
        assert pool.get_health_metrics() == {}

    @pytest.mark.asyncio
    async def test_pool_health_monitor_enabled(self) -> None:
        """Health monitor should provide metrics when enabled."""
        pool = RuntimePool(max_concurrent=2, enable_health_monitor=True)
        pool.register(
            "dummy",
            RuntimeConfig(backend_type="cli", command="echo"),
        )
        pool.get("dummy")
        metrics = pool.get_health_metrics()
        assert "dummy" in metrics
        assert "restart_count" in metrics["dummy"]
        await pool.close_all()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _HAS_CLAUDE, reason="claude CLI not installed")
    async def test_claude_session_id_capture(self) -> None:
        """Claude CLI should capture session_id from result events for resume."""
        rt = CliRuntime(
            "claude-session",
            RuntimeConfig(
                backend_type="cli",
                command="claude",
                args=["--output-format", "stream-json", "-p"],
                timeout_seconds=TIMEOUT,
                max_turns=1,
            ),
        )
        session_key = "claude-resume-test"
        events = [e async for e in rt.run_turn(SIMPLE_PROMPT, session_key)]

        has_text = any(e.type == RuntimeEventType.TEXT_DELTA for e in events)
        if has_text:
            assert session_key in rt._cli_session_ids, "Claude should capture session_id from result events"
