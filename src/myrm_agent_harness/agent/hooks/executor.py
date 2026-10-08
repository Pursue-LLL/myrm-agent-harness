"""Hook execution engine.

[INPUT]
- agent.hooks.types (POS: Hook 类型定义)
- agent.hooks.registry::HookRegistry (POS: 钩子存储，按事件分组，支持作用域生命周期)
- agent.hooks.command_gate (POS: 命令钩子安全网关(判模板、不判载荷)+载荷环境变量绑定+审批注入点)
- agent.hooks.session_access (POS: 会话级 ContextVar 访问 API，本文件头部 re-export)
- core.security.http.secure_fetch::secure_request (POS: SSRF-protected outbound HTTP)
- utils.chat_utils::extract_answer_text (POS: LLM 响应文本提取)
- utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM hook output — fences, prose, bare control chars, trailing commas)
- utils.logger_utils (POS: 日志工具)

[OUTPUT]
- HookRegistry: 从 registry 模块再导出（PEP 484 显式导出标记）
- HookExecutor: 钩子执行引擎 (4 种执行器, elapsed_ms 计时, 安全决策锁定防 deny→approve 翻转)
- get_hook_executor, set_hook_executor: ContextVar 访问器
- _SLOW_HOOK_THRESHOLD_MS: 慢 Hook 日志阈值 (500ms)

[POS]
Hook execution layer. Dispatches hooks from a registry with ContextVar-based session isolation.

"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import time
from dataclasses import replace

from myrm_agent_harness.agent.hooks.command_gate import (
    PAYLOAD_ENV_VAR,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    approve_hook_command as _approve_hook_command,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    bind_payload_reference as _bind_payload_reference,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    gate_hook_command as _gate_hook_command,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    is_strict_source as _is_strict_source,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    merged_governance_metadata as _merged_metadata,
)
from myrm_agent_harness.agent.hooks.command_gate import (
    payload_env_value as _payload_env_value,
)
from myrm_agent_harness.agent.hooks.registry import HookRegistry
from myrm_agent_harness.agent.hooks.session_access import (
    bootstrap_hook_registry,
    fire_hook,
    get_hook_executor,
    payload_from_dataclass,
    set_hook_executor,
)
from myrm_agent_harness.agent.hooks.types import (
    EMPTY_RESULT,
    HOOK_PRIORITY_SECURITY,
    AggregatedHookResult,
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HookResult,
    HttpHookDefinition,
    LLMHookDefinition,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.json_parsing import parse_llm_json_object
from myrm_agent_harness.utils.logger_utils import get_agent_logger

# Re-exports (session_access API, HookRegistry): PEP 484 explicit-export marker so
# mypy (implicit_reexport=False) accepts ``from ...hooks.executor import fire_hook``.
__all__ = [
    "HookRegistry",
    "bootstrap_hook_registry",
    "fire_hook",
    "get_hook_executor",
    "payload_from_dataclass",
    "set_hook_executor",
]

logger = get_agent_logger(__name__)

_SLOW_HOOK_THRESHOLD_MS = 500.0


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class HookExecutor:
    """Execute hooks for lifecycle events.

    Each hook runs in its own try/except — one failure never affects others.
    """

    __slots__ = ("_background_tasks", "_registry")

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def registry(self) -> HookRegistry:
        return self._registry

    def update_registry(self, registry: HookRegistry) -> None:
        self._registry = registry

    async def execute(self, event: str, payload: dict[str, object]) -> AggregatedHookResult:
        hooks = self._registry.get(event)
        if not hooks:
            return EMPTY_RESULT

        logger.info("hooks: event=%s registered=%d", event, len(hooks))
        results: list[HookResult] = []
        # Highest priority whose decision is already locked by a security hook.
        # Lower-priority hooks must not override a locked ``updated_input``.
        locked_priority: int | None = None
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
            result = replace(result, elapsed_ms=elapsed_ms, metadata=_merged_metadata(result.metadata, hook))
            if hook.priority >= HOOK_PRIORITY_SECURITY and (result.blocked or result.updated_input is not None):
                locked_priority = hook.priority
            elif locked_priority is not None and hook.priority < locked_priority and result.updated_input is not None:
                # A user-authored hook may not rewrite input that a security
                # hook has already rewritten or guarded (deny→approve flip).
                result = replace(result, updated_input=None)
            if elapsed_ms > _SLOW_HOOK_THRESHOLD_MS:
                logger.warning(
                    "Slow hook [%s] %s took %.0fms (>%.0fms)",
                    event,
                    hook.type,
                    elapsed_ms,
                    _SLOW_HOOK_THRESHOLD_MS,
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
        from myrm_agent_harness.toolkits.code_execution.security.env_isolation import (
            EnvInheritPolicy,
            build_isolated_child_env,
        )

        refusal = _gate_hook_command(hook.command, strict=_is_strict_source(hook))
        if refusal is not None:
            # The gate judges the hook, not the event: a refused command never
            # blocks the main flow unless the hook itself opted into fail-closed.
            if await _approve_hook_command(hook, event, hook.command):
                logger.info("hooks: command hook approved via approver [event=%s source=%s]", event, hook.source.value)
            else:
                logger.warning(
                    "hooks: command hook refused by safety gate [event=%s source=%s] — %s",
                    event,
                    hook.source.value,
                    refusal,
                )
                return HookResult(
                    hook_type="command",
                    success=False,
                    blocked=hook.block_on_failure,
                    reason=f"Command refused by hook safety gate: {refusal}",
                    metadata={"gate_blocked": True},
                )

        # Event data reaches the command only through the env var (see bind_payload_reference) and
        # stdin. The env var is clipped to fit one environment string; stdin carries the complete payload.
        command = _bind_payload_reference(hook.command)
        payload_json = json.dumps(payload, default=str, ensure_ascii=True)
        extra_env = {
            "HOOK_EVENT": event,
            PAYLOAD_ENV_VAR: _payload_env_value(payload_json),
        }
        env = build_isolated_child_env(
            base_env=None,
            extra_env=extra_env,
            inherit_policy=EnvInheritPolicy.CORE,
        )

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(payload_json.encode("utf-8")), timeout=hook.timeout_seconds
            )
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
        if hook.fire_and_forget:
            task = asyncio.create_task(self._http_fire_and_forget(hook, event, payload))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return HookResult(hook_type="http", success=True, output="fire-and-forget dispatched")

        return await self._http_send(hook, event, payload)

    async def _http_fire_and_forget(self, hook: HttpHookDefinition, event: str, payload: dict[str, object]) -> None:
        """Background task for fire-and-forget HTTP hooks; errors are logged only."""
        try:
            await self._http_send(hook, event, payload)
        except Exception as exc:
            logger.warning("Fire-and-forget HTTP hook [%s] %s failed: %s", event, hook.url[:60], exc)

    async def _http_send(self, hook: HttpHookDefinition, event: str, payload: dict[str, object]) -> HookResult:
        from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
        from myrm_agent_harness.core.security.http.secure_fetch import secure_request

        try:
            import httpx  # noqa: F401  # optional dependency guard
        except (ImportError, TypeError):
            return HookResult(
                hook_type="http",
                success=False,
                blocked=hook.block_on_failure,
                reason="httpx not installed or broken — required for Http hooks",
            )

        headers = dict(hook.headers)
        body = json.dumps({"event": event, "payload": payload}, default=str, ensure_ascii=True)

        if hook.secret:
            import hashlib
            import hmac as _hmac

            sig = _hmac.new(hook.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={sig}"

        try:
            from myrm_agent_harness.infra.tls_compat import create_httpx_client

            async with create_httpx_client(timeout=hook.timeout_seconds, follow_redirects=False) as client:
                response = await secure_request(
                    client,
                    "POST",
                    hook.url,
                    content=body,
                    headers={**headers, "Content-Type": "application/json"},
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
            from myrm_agent_harness.toolkits.llms import create_litellm_model

            model = hook.model or os.environ.get("MYRM_HOOK_MODEL")
            if model is None:
                return HookResult(
                    hook_type="llm",
                    success=False,
                    blocked=hook.block_on_failure,
                    reason="LLM hook requires a model (set 'model' or MYRM_HOOK_MODEL)",
                )
            llm = create_litellm_model(model=model)
            response = await asyncio.wait_for(
                llm.ainvoke(f"{prefix}\n\n{prompt}"),
                timeout=hook.timeout_seconds,
            )
            # 兼容 reasoning 模型 content 空回退（DeepSeek-R1/Qwen3 等）
            text = extract_answer_text(response)
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
            reason=str(parsed.get("reason", "LLM hook rejected the event")),
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
    # ``|`` separates alternative patterns (``bash_*|write_file_tool``); tool names never contain it.
    return any(fnmatch.fnmatch(subject, pattern) for pattern in hook.matcher.split("|"))


def _inject_arguments(template: str, payload: dict[str, object]) -> str:
    return template.replace("$ARGUMENTS", json.dumps(payload, default=str, ensure_ascii=True))


def _parse_hook_json(text: str) -> dict[str, object]:
    try:
        parsed = parse_llm_json_object(text)
        if parsed is not None and isinstance(parsed.get("ok"), bool):
            return parsed
    except (ValueError, TypeError):
        pass
    lowered = text.strip().lower()
    if lowered in {"ok", "true", "yes"}:
        return {"ok": True}
    return {"ok": False, "reason": text.strip()[:200] or "Invalid JSON from LLM hook"}


# ---------------------------------------------------------------------------
# ContextVar-based session-scoped access
# ---------------------------------------------------------------------------
# Definitions live in session_access.py; both import paths
# (``hooks.session_access`` / ``hooks.executor``) expose the same API.
