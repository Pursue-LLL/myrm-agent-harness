"""Hook registry and execution engine.

[INPUT]
- agent.hooks.types (POS: Hook 类型定义)
- core.security.http.secure_fetch::secure_request (POS: SSRF-protected outbound HTTP)
- utils.logger_utils (POS: 日志工具)

[OUTPUT]
- HookRegistry: 钩子注册管理器
- HookExecutor: 钩子执行引擎 (4 种执行器, elapsed_ms 计时)
- get_hook_executor, set_hook_executor: ContextVar 访问器
- _SLOW_HOOK_THRESHOLD_MS: 慢 Hook 日志阈值 (500ms)

[POS]
Hook execution layer. Manages hook registration and execution with ContextVar-based session isolation.

"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import shlex
import time
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import asdict, replace

from myrm_agent_harness.agent.hooks.types import (
    EMPTY_RESULT,
    AggregatedHookResult,
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HookResult,
    HttpHookDefinition,
    LLMHookDefinition,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_SLOW_HOOK_THRESHOLD_MS = 500.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class HookRegistry:
    """Store hooks grouped by event name.

    Accepts both HookEvent enum values and arbitrary strings for custom events.
    """

    __slots__ = "_hooks"

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookDefinition]] = defaultdict(list)

    def register(self, event: str, hook: HookDefinition) -> None:
        self._hooks[event].append(hook)

    def get(self, event: str) -> list[HookDefinition]:
        return list(self._hooks.get(event, []))

    def clear(self) -> None:
        self._hooks.clear()

    @property
    def total_count(self) -> int:
        return sum(len(hooks) for hooks in self._hooks.values())

    def summary(self) -> str:
        lines: list[str] = []
        for event, hooks in sorted(self._hooks.items()):
            if not hooks:
                continue
            lines.append(f"{event}:")
            for hook in hooks:
                matcher = hook.matcher or "*"
                detail = _hook_detail(hook)
                lines.append(f"  - [{hook.type}] matcher={matcher} {detail}")
        return "\n".join(lines)


def _hook_detail(hook: HookDefinition) -> str:
    if isinstance(hook, CallableHookDefinition):
        fn_name = getattr(hook.fn, "__name__", repr(hook.fn))
        return f"fn={fn_name}"
    if isinstance(hook, CommandHookDefinition):
        return f"cmd={hook.command[:60]}"
    if isinstance(hook, HttpHookDefinition):
        return f"url={hook.url[:60]}"
    if isinstance(hook, LLMHookDefinition):
        return f"depth={hook.depth} prompt={hook.prompt[:40]}"
    return ""


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class HookExecutor:
    """Execute hooks for lifecycle events.

    Each hook runs in its own try/except — one failure never affects others.
    """

    __slots__ = "_registry"

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> HookRegistry:
        return self._registry

    def update_registry(self, registry: HookRegistry) -> None:
        self._registry = registry

    async def execute(self, event: str, payload: dict[str, object]) -> AggregatedHookResult:
        hooks = self._registry.get(event)
        if not hooks:
            return EMPTY_RESULT

        results: list[HookResult] = []
        for hook in hooks:
            if not _matches_hook(hook, payload):
                continue
            t0 = time.monotonic()
            try:
                result = await self._dispatch(hook, event, payload)
            except Exception as exc:
                logger.warning("Hook [%s] %s raised: %s", event, hook.type, exc)
                result = HookResult(
                    hook_type=hook.type,
                    success=False,
                    blocked=hook.block_on_failure,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            elapsed_ms = (time.monotonic() - t0) * 1000
            result = replace(result, elapsed_ms=elapsed_ms)
            if elapsed_ms > _SLOW_HOOK_THRESHOLD_MS:
                logger.warning(
                    "Slow hook [%s] %s took %.0fms (>%.0fms)",
                    event, hook.type, elapsed_ms, _SLOW_HOOK_THRESHOLD_MS,
                )
            results.append(result)
            if result.blocked:
                break

        agg = AggregatedHookResult(results=tuple(results))
        return await self._spill_oversized_contexts(agg, payload)

    async def _dispatch(self, hook: HookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        if isinstance(hook, CallableHookDefinition):
            return await self._run_callable(hook, event, payload)
        if isinstance(hook, CommandHookDefinition):
            return await self._run_command(hook, event, payload)
        if isinstance(hook, HttpHookDefinition):
            return await self._run_http(hook, event, payload)
        if isinstance(hook, LLMHookDefinition):
            return await self._run_llm(hook, event, payload)
        return HookResult(hook_type="unknown", success=False, reason="Unknown hook type")

    # -- Callable --

    async def _run_callable(self, hook: CallableHookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        return await asyncio.wait_for(hook.fn(event, payload), timeout=hook.timeout_seconds)

    # -- Command --

    async def _run_command(self, hook: CommandHookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        command = _inject_arguments(hook.command, payload, shell_escape=True)
        env = {
            **os.environ,
            "HOOK_EVENT": event,
            "HOOK_PAYLOAD": json.dumps(payload, default=str, ensure_ascii=True),
        }

        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=hook.timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            return HookResult(
                hook_type="command",
                success=False,
                blocked=hook.block_on_failure,
                reason=f"Command hook timed out after {hook.timeout_seconds}s",
            )

        output = "\n".join(
            part
            for part in (
                stdout_bytes.decode("utf-8", errors="replace").strip(),
                stderr_bytes.decode("utf-8", errors="replace").strip(),
            )
            if part
        )
        success = process.returncode == 0
        return HookResult(
            hook_type="command",
            success=success,
            output=output,
            blocked=hook.block_on_failure and not success,
            reason=output or f"Exit code {process.returncode}",
            metadata={"returncode": process.returncode},
        )

    # -- HTTP --

    async def _run_http(self, hook: HttpHookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
        from myrm_agent_harness.core.security.http.secure_fetch import secure_request

        try:
            import httpx
        except (ImportError, TypeError):
            return HookResult(
                hook_type="http",
                success=False,
                blocked=hook.block_on_failure,
                reason="httpx not installed or broken — required for Http hooks",
            )

        headers = dict(hook.headers)
        try:
            from myrm_agent_harness.infra.tls_compat import create_httpx_client

            async with create_httpx_client(timeout=hook.timeout_seconds, follow_redirects=False) as client:
                response = await secure_request(
                    client,
                    "POST",
                    hook.url,
                    json={"event": event, "payload": payload},
                    headers=headers,
                    timeout=hook.timeout_seconds,
                )
            success = response.is_success
            return HookResult(
                hook_type="http",
                success=success,
                output=response.text[:500],
                blocked=hook.block_on_failure and not success,
                reason=response.text[:200] or f"HTTP {response.status_code}",
                metadata={"status_code": response.status_code},
            )
        except SSRFSecurityError as exc:
            return HookResult(
                hook_type="http",
                success=False,
                blocked=hook.block_on_failure,
                reason=f"SSRF blocked: {exc}",
            )
        except Exception as exc:
            return HookResult(hook_type="http", success=False, blocked=hook.block_on_failure, reason=str(exc))

    # -- LLM --

    async def _run_llm(self, hook: LLMHookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        prompt = _inject_arguments(hook.prompt, payload)
        prefix = (
            "You are validating whether a hook condition passes. "
            'Return strict JSON: {"ok": true} or {"ok": false, "reason": "..."}.'
        )
        if hook.depth == "thorough":
            prefix += " Reason carefully over the full payload before deciding."

        try:
            from myrm_agent_harness.toolkits.llms.adapters.converters import get_default_llm

            llm = get_default_llm(model_name=hook.model)
            response = await asyncio.wait_for(llm.ainvoke(f"{prefix}\n\n{prompt}"), timeout=hook.timeout_seconds)
            text = response.content if hasattr(response, "content") else str(response)
            if not isinstance(text, str):
                text = str(text)
        except (ImportError, TypeError):
            return HookResult(
                hook_type="llm",
                success=False,
                blocked=hook.block_on_failure,
                reason="LLM adapter not available or broken",
            )
        except Exception as exc:
            return HookResult(
                hook_type="llm", success=False, blocked=hook.block_on_failure, reason=f"LLM hook error: {exc}"
            )

        parsed = _parse_hook_json(text)
        if parsed["ok"]:
            return HookResult(hook_type="llm", success=True, output=text[:200])
        return HookResult(
            hook_type="llm",
            success=False,
            output=text[:200],
            blocked=hook.block_on_failure,
            reason=parsed.get("reason", "LLM hook rejected the event"),
        )

    # -- Output spilling --

    async def _spill_oversized_contexts(
        self, agg: AggregatedHookResult, payload: dict[str, object]
    ) -> AggregatedHookResult:
        """Spill oversized additional_context to disk, replacing with preview."""
        contexts = agg.additional_contexts
        if not contexts:
            return agg

        from myrm_agent_harness.agent.hooks.output_spiller import HOOK_OUTPUT_TOKEN_LIMIT, HookOutputSpiller
        from myrm_agent_harness.utils.text_utils import get_token_count

        # Quick check: skip spilling if all contexts are under limit
        if all(get_token_count(c) <= HOOK_OUTPUT_TOKEN_LIMIT for c in contexts):
            return agg

        session_id = str(payload.get("session_id", ""))
        spiller = HookOutputSpiller()

        new_results: list[HookResult] = []
        for r in agg.results:
            if r.additional_context and get_token_count(r.additional_context) > HOOK_OUTPUT_TOKEN_LIMIT:
                spilled = await spiller.maybe_spill_text(r.additional_context, session_id)
                new_results.append(replace(r, additional_context=spilled))
            else:
                new_results.append(r)

        return AggregatedHookResult(results=tuple(new_results))


def _matches_hook(hook: HookDefinition, payload: dict[str, object]) -> bool:
    if not hook.matcher:
        return True
    subject = str(payload.get("tool_name", ""))
    return fnmatch.fnmatch(subject, hook.matcher)


def _inject_arguments(template: str, payload: dict[str, object], *, shell_escape: bool = False) -> str:
    serialized = json.dumps(payload, default=str, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)
    return template.replace("$ARGUMENTS", serialized)


def _parse_hook_json(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("ok"), bool):
            return parsed
    except json.JSONDecodeError:
        pass
    lowered = text.strip().lower()
    if lowered in {"ok", "true", "yes"}:
        return {"ok": True}
    return {"ok": False, "reason": text.strip()[:200] or "Invalid JSON from LLM hook"}


# ---------------------------------------------------------------------------
# ContextVar-based session-scoped access
# ---------------------------------------------------------------------------


_executor_var: ContextVar[HookExecutor | None] = ContextVar("hook_executor", default=None)


def get_hook_executor() -> HookExecutor | None:
    """Get the session-scoped HookExecutor, or None if not configured."""
    return _executor_var.get()


def set_hook_executor(executor: HookExecutor | None) -> None:
    """Set the session-scoped HookExecutor."""
    _executor_var.set(executor)


async def fire_hook(event: str, payload: dict[str, object]) -> AggregatedHookResult:
    """Convenience: fire a hook event on the current session's executor.

    Returns EMPTY_RESULT if no executor is configured — zero overhead when
    hooks are not used.
    """
    executor = _executor_var.get()
    if executor is None:
        return EMPTY_RESULT
    return await executor.execute(event, payload)


def payload_from_dataclass(obj: object) -> dict[str, object]:
    """Convert a frozen dataclass payload to dict for hook execution."""
    return asdict(obj)  # type: ignore[arg-type]


def bootstrap_hook_registry() -> HookRegistry:
    """Get or create the session-scoped HookRegistry.

    Ensures that the registry is a singleton per session and avoids
    duplicate registration of core framework hooks.
    """
    executor = get_hook_executor()
    if executor is not None:
        return executor.registry

    registry = HookRegistry()
    set_hook_executor(HookExecutor(registry))
    return registry
