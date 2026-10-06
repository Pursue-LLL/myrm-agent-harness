"""Branch coverage for the command gate, LLM hooks, and oversized-context spilling.

Each case targets a branch the main suite in test_hooks.py leaves uncovered:
gate BLOCK-pattern refusal, approver failure paths (raising / silent), LLM-hook
execution outcomes, httpx guard, verdict-parsing fallback, and the spilling
loop in execute().
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from myrm_agent_harness.agent.hooks import (
    CallableHookDefinition,
    CommandHookDefinition,
    HookEvent,
    HookExecutor,
    HookRegistry,
    HookResult,
    HookSource,
    LLMHookDefinition,
    set_command_hook_approver,
)
from myrm_agent_harness.agent.hooks.command_gate import approve_hook_command
from myrm_agent_harness.agent.hooks.executor import _hook_detail, _parse_hook_json
from myrm_agent_harness.agent.hooks.output_spiller import HookOutputSpiller
from myrm_agent_harness.agent.hooks.types import HttpHookDefinition


class TestCommandGateRefusals:
    """Refusal variants of gate_hook_command reached through the executor."""

    @pytest.mark.asyncio
    async def test_gate_blocks_block_level_pattern_even_for_builtin(self):
        """BLOCK-level analysis is refused regardless of source (non-strict path)."""
        registry = HookRegistry()
        registry.register(
            HookEvent.SESSION_START,
            CommandHookDefinition(command="history -c", source=HookSource.BUILTIN),
        )
        result = await HookExecutor(registry).execute(HookEvent.SESSION_START, {})
        assert result.results[0].success is False
        assert result.results[0].metadata["gate_blocked"] is True
        assert "safety gate" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_gate_fails_closed_when_approver_raises(self):
        """A crashing approver must not widen the gate: refusal stands (False)."""

        async def _boom(hook, event: str, command: str) -> bool:
            raise RuntimeError("approval ui crashed")

        set_command_hook_approver(_boom)
        try:
            hook = CommandHookDefinition(command="eval true", source=HookSource.SKILL)
            approved = await approve_hook_command(hook, "SessionStart", "eval true")
        finally:
            set_command_hook_approver(None)
        assert approved is False

    @pytest.mark.asyncio
    async def test_gate_fails_closed_when_approver_never_answers(self):
        """A silent approver is bounded by the hook timeout and counts as a refusal."""

        async def _hang(hook, event: str, command: str) -> bool:
            await asyncio.sleep(30)
            return True

        set_command_hook_approver(_hang)
        try:
            hook = CommandHookDefinition(command="eval true", source=HookSource.SKILL, timeout_seconds=1)
            approved = await approve_hook_command(hook, "SessionStart", "eval true")
        finally:
            set_command_hook_approver(None)
        assert approved is False


class TestLLMHookExecution:
    """All four outcomes of _run_llm plus the adapter/dependency guards."""

    @staticmethod
    def _register_llm(registry: HookRegistry, **overrides: object) -> LLMHookDefinition:
        model = overrides.pop("model", "test-model")
        hook = LLMHookDefinition(prompt="is $ARGUMENTS safe?", model=model, **overrides)
        registry.register(HookEvent.PRE_TOOL_USE, hook)
        return hook

    @staticmethod
    def _install_model(monkeypatch: pytest.MonkeyPatch, response_content: str, *, delay: float = 0.0) -> list[str]:
        """Patch the litellm adapter with a stub; return captured prompts."""

        class _StubLLM:
            async def ainvoke(self, prompt: str) -> object:
                await asyncio.sleep(delay)
                return SimpleNamespace(content=response_content)

        captured: list[str] = []
        stub = _StubLLM()

        async def _invoke_and_capture(prompt: str) -> object:
            captured.append(prompt)
            return await stub.ainvoke(prompt)

        def _fake_create(*, model: str) -> object:
            return SimpleNamespace(ainvoke=_invoke_and_capture)

        monkeypatch.setattr("myrm_agent_harness.toolkits.llms.create_litellm_model", _fake_create)
        return captured

    @pytest.mark.asyncio
    async def test_llm_hook_missing_model_fails_closed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MYRM_HOOK_MODEL", raising=False)
        registry = HookRegistry()
        self._register_llm(registry, model=None)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].success is False
        assert "requires a model" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_llm_hook_adapter_import_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, "myrm_agent_harness.toolkits.llms", None)
        registry = HookRegistry()
        self._register_llm(registry)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].success is False
        assert "adapter not available" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_llm_hook_ok_true_passes(self, monkeypatch: pytest.MonkeyPatch):
        captured = self._install_model(monkeypatch, '{"ok": true}')
        registry = HookRegistry()
        self._register_llm(registry)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {"tool_name": "Read"})
        assert result.results[0].success is True
        assert "validating whether a hook condition passes" in captured[0]

    @pytest.mark.asyncio
    async def test_llm_hook_thorough_prompt_asks_for_deep_reasoning(self, monkeypatch: pytest.MonkeyPatch):
        captured = self._install_model(monkeypatch, '{"ok": true}')
        registry = HookRegistry()
        self._register_llm(registry, depth="thorough")
        await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert "Reason carefully" in captured[0]

    @pytest.mark.asyncio
    async def test_llm_hook_ok_false_blocks_when_configured(self, monkeypatch: pytest.MonkeyPatch):
        self._install_model(monkeypatch, '{"ok": false, "reason": "nope"}')
        registry = HookRegistry()
        self._register_llm(registry, block_on_failure=True)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].success is False
        assert result.results[0].blocked is True
        assert result.results[0].reason == "nope"

    @pytest.mark.asyncio
    async def test_llm_hook_plain_ok_text_accepted(self, monkeypatch: pytest.MonkeyPatch):
        """Non-JSON "ok" falls back to boolean acceptance."""
        self._install_model(monkeypatch, "ok")
        registry = HookRegistry()
        self._register_llm(registry)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].success is True

    @pytest.mark.asyncio
    async def test_llm_hook_timeout_treated_as_error(self, monkeypatch: pytest.MonkeyPatch):
        self._install_model(monkeypatch, '{"ok": true}', delay=2.0)
        registry = HookRegistry()
        self._register_llm(registry, timeout_seconds=1)
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].success is False
        assert "LLM hook error" in result.results[0].reason

    def test_hook_detail_llm_branch(self):
        detail = _hook_detail(LLMHookDefinition(prompt="validate", depth="quick"))
        assert "depth=quick" in detail
        assert "prompt=validate" in detail


class TestDispatchGuardsAndSpilling:
    """Unknown-type dispatch, httpx guard, summary edge, and the spilling loop."""

    @pytest.mark.asyncio
    async def test_dispatch_rejects_unknown_hook_type(self):
        executor = HookExecutor(HookRegistry())
        result = await executor._dispatch(SimpleNamespace(), HookEvent.SESSION_START, {})  # type: ignore[arg-type]
        assert result.success is False
        assert result.hook_type == "unknown"

    @pytest.mark.asyncio
    async def test_http_hook_requires_httpx(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, "httpx", None)
        registry = HookRegistry()
        registry.register(
            HookEvent.SESSION_START,
            HttpHookDefinition(url="https://example.com/hook", source=HookSource.SKILL),
        )
        result = await HookExecutor(registry).execute(HookEvent.SESSION_START, {})
        assert result.results[0].success is False
        assert "httpx not installed" in result.results[0].reason

    def test_summary_omits_events_left_with_no_hooks(self):
        """A defaultdict read materialises an empty slot; summary must not list it."""
        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CommandHookDefinition(command="echo hi"))
        _ = registry._hooks[HookEvent.SESSION_END]
        summary = registry.summary()
        assert "session_start" in summary
        assert "session_end" not in summary

    @staticmethod
    def _patch_spiller(monkeypatch: pytest.MonkeyPatch, *, token_limit: int) -> None:
        """Lower the spill threshold and replace disk I/O with a fixed reference."""

        async def _fake_spill(self: HookOutputSpiller, text: str, session_id: str) -> str:
            return "SPILLED-REF"

        monkeypatch.setattr("myrm_agent_harness.agent.hooks.output_spiller.HOOK_OUTPUT_TOKEN_LIMIT", token_limit)
        monkeypatch.setattr(HookOutputSpiller, "maybe_spill_text", _fake_spill)

    @staticmethod
    def _context_hook(context: str) -> CallableHookDefinition:
        async def _hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(hook_type="callable", success=True, additional_context=context)

        return CallableHookDefinition(fn=_hook)

    @pytest.mark.asyncio
    async def test_execute_spills_oversized_additional_context(self, monkeypatch: pytest.MonkeyPatch):
        self._patch_spiller(monkeypatch, token_limit=0)
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, self._context_hook("x" * 5000))
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {"session_id": "cov-spill"})
        assert result.results[0].additional_context == "SPILLED-REF"

    @pytest.mark.asyncio
    async def test_execute_leaves_small_additional_context_untouched(self):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, self._context_hook("short note"))
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert result.results[0].additional_context == "short note"

    @pytest.mark.asyncio
    async def test_execute_spills_only_the_oversized_context(self, monkeypatch: pytest.MonkeyPatch):
        """Mixed batch: the large context is replaced, the small one is preserved verbatim."""
        self._patch_spiller(monkeypatch, token_limit=50)
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, self._context_hook("word " * 500))
        registry.register(HookEvent.PRE_TOOL_USE, self._context_hook("tiny note"))
        result = await HookExecutor(registry).execute(HookEvent.PRE_TOOL_USE, {})
        assert [r.additional_context for r in result.results] == ["SPILLED-REF", "tiny note"]


class TestHookJsonParsing:
    def test_parse_hook_json_survives_extractor_exception(self, monkeypatch: pytest.MonkeyPatch):
        """A raising JSON extractor degrades to the plain-text verdict heuristics."""

        def _raise(text: str) -> dict[str, object] | None:
            raise ValueError("malformed")

        monkeypatch.setattr("myrm_agent_harness.agent.hooks.executor.parse_llm_json_object", _raise)
        assert _parse_hook_json("ok") == {"ok": True}
        rejected = _parse_hook_json("garbled verdict")
        assert rejected["ok"] is False
        assert rejected["reason"] == "garbled verdict"
