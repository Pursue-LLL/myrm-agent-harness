"""Delegate tasks to external ACP-compatible agents.

Allows any LangChain agent to hand off work to Claude Code, Codex CLI,
Gemini CLI, or any other agent that implements the ACP protocol, SDK,
or CLI interface via the unified RuntimePool.

[INPUT]
- utils.runtime.progress_sink::ToolProgressSink (POS: ContextVar  Agent SSE  BaseAgent)
- agent.streaming.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- DelegateUsage: Token usage statistics from an external agent delegation.
- DelegateMeta: Metadata collected during an external agent delegation turn.
- create_delegate_to_agent_tool: Create the delegate_to_agent tool.

[POS]
Delegate tasks to external ACP-compatible agents.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, NotRequired, TypedDict
from uuid import uuid4

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.toolkits.acp.runtime._base import truncate_response
from myrm_agent_harness.toolkits.acp.types import RuntimeEventType
from myrm_agent_harness.utils.runtime.cancellation import get_cancel_token
from myrm_agent_harness.utils.runtime.progress_sink import ToolProgressSink, get_tool_progress_sink

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.toolkits.acp.runtime.pool import RuntimePool


class DelegateUsage(TypedDict):
    """Token usage statistics from an external agent delegation."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class DelegateMeta(TypedDict):
    """Metadata collected during an external agent delegation turn."""

    tool_calls: int
    errors: int
    usage: NotRequired[DelegateUsage]


logger = logging.getLogger(__name__)

MAX_TASK_BYTES = 2 * 1024 * 1024  # 2 MB — aligned with openclaw's MAX_PROMPT_BYTES
_MAX_RETRIES = 1
_DEFAULT_MAX_TURNS = 25


def _build_agent_listing(pool: RuntimePool) -> str:
    """Build a formatted listing of available agents with descriptions."""
    names = pool.available_backends
    if not names:
        return "(none configured)"
    lines: list[str] = []
    for name in names:
        cfg = pool.get_config(name)
        desc = cfg.description if cfg else ""
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    return "\n".join(lines)


def create_delegate_to_agent_tool(
    pool: RuntimePool,
    *,
    cwd: str | None = None,
    session_scope: str | None = None,
) -> BaseTool:
    """Create the delegate_to_agent tool.

    Args:
        pool: Pre-configured RuntimePool with registered backends.
        cwd: Working directory injected as context into delegated tasks.
        session_scope: Optional chat/session id for stable CLI resume keys.

    Returns:
        A LangChain tool function.
    """
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

    effective_cwd = cwd or str(WorkspacePathResolver.resolve_workspace_root())

    tool_description = """Delegate a task to an external coding agent.

Use this tool when you need another AI agent (Claude Code, Codex, Gemini CLI, etc.)
to perform a coding task. The external agent runs as a separate process with its own
context and capabilities.

## Parameters
- agent_name: Name of the external agent (must match a configured backend in Settings).
- task: Clear, complete description of what the agent should do.
  Include all necessary context — the external agent has NO access to your conversation.
- mode: 'persistent' (default) reuses the session for follow-ups;
  'oneshot' creates a fresh session each time.

## When to use
- Complex coding tasks that benefit from a specialized agent's capabilities
- Tasks requiring different tool sets or model capabilities
- Parallel work delegation

## Notes
- The external agent runs independently — provide ALL context in the task.
- Response is the agent's complete text output (tool calls are summarized).
- Each agent has a max-turns safety limit (default 25).
- If agent_name is unknown, the error lists currently configured backends.
"""

    class DelegateInput(BaseModel):
        agent_name: str = Field(description="Name of the external agent")
        task: str = Field(description="Complete task description with full context")
        mode: str = Field(default="persistent", description="'persistent' or 'oneshot'")

    @tool("delegate_to_agent_tool", description=tool_description, args_schema=DelegateInput)
    async def delegate_to_agent_func(
        agent_name: str,
        task: str,
        mode: str = "persistent",
    ) -> str:
        """Delegate a task to an external agent and return its response."""
        if mode not in ("persistent", "oneshot"):
            return f"[error] Invalid mode '{mode}'. Use 'persistent' or 'oneshot'."

        task_size = len(task.encode("utf-8"))
        if task_size > MAX_TASK_BYTES:
            return f"[error] Task too large ({task_size} bytes). Max: {MAX_TASK_BYTES} bytes."

        enriched_task = f"{task}\n\n[Context: cwd={effective_cwd}]"

        logger.info("acp_delegate agent=%s mode=%s task_length=%d", agent_name, mode, len(task))

        t0 = time.monotonic()
        last_error: str = ""
        for attempt in range(_MAX_RETRIES + 1):
            try:
                result, meta = await _run_turn_and_collect(
                    pool,
                    agent_name,
                    enriched_task,
                    mode=mode,
                    session_scope=session_scope,
                )
                elapsed = time.monotonic() - t0
                truncated = result.endswith("[truncated — response exceeded limit]")
                usage = meta.get("usage")

                log_parts = [
                    f"agent={agent_name}",
                    f"elapsed={elapsed:.1f}s",
                    f"chars={len(result)}",
                    f"tools={meta['tool_calls']}",
                    f"errors={meta['errors']}",
                    f"truncated={truncated}",
                ]
                if usage:
                    log_parts.append(f"tokens={usage['total_tokens']}")
                logger.info("acp_delegate_done %s", " ".join(log_parts))

                summary = f"agent={agent_name}, elapsed={elapsed:.1f}s, truncated={truncated}"
                if meta["tool_calls"]:
                    summary += f", tool_calls={meta['tool_calls']}"
                if usage:
                    summary += f", tokens={usage['total_tokens']}"
                    sink = get_tool_progress_sink()
                    if sink:
                        cfg = pool.get_config(agent_name)
                        auth_mode = cfg.auth_mode if cfg else "subscription"
                        await sink.emit(
                            {
                                "type": AgentEventType.TOKEN_USAGE.value,
                                "data": {
                                    "source": f"delegate:{agent_name}",
                                    "input_tokens": usage["input_tokens"],
                                    "output_tokens": usage["output_tokens"],
                                    "total_tokens": usage["total_tokens"],
                                    # Subscription delegations run on the user's own plan, so they
                                    # carry no metered API cost in our ledger; api_key mode is billable.
                                    "auth_mode": auth_mode,
                                    "billable": auth_mode == "api_key",
                                },
                            }
                        )

                return f"{result}\n\n[Delegation: {summary}]"
            except KeyError as exc:
                available = ", ".join(pool.available_backends) or "(none configured)"
                return f"[error] {exc}. Available backends: {available}"
            except Exception as exc:
                elapsed = time.monotonic() - t0
                retryable = getattr(getattr(exc, "__cause__", None), "retryable", False) or getattr(
                    exc, "retryable", False
                )
                if retryable and attempt < _MAX_RETRIES:
                    logger.warning(
                        "acp_delegate_retry agent=%s attempt=%d error=%s",
                        agent_name,
                        attempt + 1,
                        exc,
                    )
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue

                logger.error("acp_delegate_error agent=%s error=%s", agent_name, exc, exc_info=True)
                return f"[error] Delegation to '{agent_name}' failed: {type(exc).__name__}: {exc}"

        return f"[error] Delegation to '{agent_name}' failed after {_MAX_RETRIES + 1} attempts: {last_error}"

    return delegate_to_agent_func


def _as_int(value: object) -> int:
    """Best-effort int coercion for loosely-typed (``object``) event payloads."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return 0


async def _run_turn_and_collect(
    pool: RuntimePool,
    agent_name: str,
    task: str,
    *,
    mode: str,
    session_scope: str | None = None,
) -> tuple[str, DelegateMeta]:
    """Stream events from pool.run_turn(), collect text, and track metadata.

    When a ToolProgressSink is available (via ContextVar, set by BaseAgent.run),
    intermediate events (tool starts, status updates) are pushed directly into
    the Agent's SSE stream, giving the frontend real-time delegation progress.

    Supports cancellation propagation: if the parent Agent's CancellationToken
    fires, the external agent process is terminated via pool.cancel().
    """
    if mode == "oneshot":
        session_id = f"{agent_name}-oneshot-{uuid4().hex}"
    elif session_scope:
        session_id = f"{agent_name}-{session_scope}"
    else:
        session_id = f"{agent_name}-default"

    config = pool.get_config(agent_name)
    max_turns = config.max_turns if config else _DEFAULT_MAX_TURNS

    sink: ToolProgressSink | None = get_tool_progress_sink()
    cancel_token = get_cancel_token()
    text_parts: list[str] = []
    tool_calls = 0
    error_count = 0
    input_tokens = 0
    output_tokens = 0
    was_cancelled = False
    turns_exceeded = False

    async for event in pool.run_turn(agent_name, task, session_id=session_id, mode=mode):
        if cancel_token and cancel_token.is_cancelled:
            logger.warning("acp_delegate_cancelled agent=%s session=%s", agent_name, session_id)
            await pool.cancel(agent_name, session_id)
            was_cancelled = True
            break

        if event.type == RuntimeEventType.TEXT_DELTA:
            content = event.data.get("content")
            if isinstance(content, str):
                text_parts.append(content)
        elif event.type == RuntimeEventType.REASONING_DELTA:
            if sink:
                reasoning_content = event.data.get("content")
                if isinstance(reasoning_content, str) and reasoning_content:
                    await sink.emit(
                        {
                            "type": AgentEventType.REASONING.value,
                            "data": {"content": reasoning_content, "source": f"delegate:{agent_name}"},
                        }
                    )
        elif event.type == RuntimeEventType.TOOL_START:
            tool_calls += 1
            tool_name = event.data.get("tool_name", "unknown")
            logger.info("acp_delegate_tool agent=%s tool=%s (%d/%d)", agent_name, tool_name, tool_calls, max_turns)
            if max_turns > 0 and tool_calls >= max_turns:
                logger.warning(
                    "acp_delegate_max_turns agent=%s turns=%d limit=%d",
                    agent_name,
                    tool_calls,
                    max_turns,
                )
                await pool.cancel(agent_name, session_id)
                turns_exceeded = True
                break
            if sink:
                await sink.emit(
                    {
                        "type": AgentEventType.TASKS_STEPS.value,
                        "step_key": f"delegation_{agent_name}_tool",
                        "tool_name": f"delegate:{agent_name}",
                        "data": [{"text": f"{agent_name}: {tool_name}"}],
                    }
                )
        elif event.type == RuntimeEventType.USAGE_UPDATE:
            input_tokens += _as_int(event.data.get("input_tokens"))
            output_tokens += _as_int(event.data.get("output_tokens"))
        elif event.type == RuntimeEventType.ERROR:
            error_count += 1
            error_data = event.data.get("error")
            if hasattr(error_data, "message"):
                logger.warning("acp_delegate_event_error agent=%s msg=%s", agent_name, error_data.message)
                exc = RuntimeError(error_data.message)
                exc.retryable = getattr(error_data, "retryable", False)  # type: ignore[attr-defined]
                raise exc
        elif event.type == RuntimeEventType.STATUS_UPDATE:
            status = event.data.get("status", "")
            message = event.data.get("message", "")
            logger.info("acp_delegate_status agent=%s status=%s msg=%s", agent_name, status, message)
            if sink:
                await sink.emit(
                    {
                        "type": AgentEventType.TASKS_STEPS.value,
                        "step_key": f"delegation_{agent_name}_status",
                        "tool_name": f"delegate:{agent_name}",
                        "data": [{"text": f"{agent_name}: {status}" + (f" — {message}" if message else "")}],
                    }
                )

    max_chars = config.max_response_chars if config else 50_000
    collected = "".join(text_parts)
    if was_cancelled:
        collected += "\n\n[cancelled — user aborted delegation]"
    elif turns_exceeded:
        collected += f"\n\n[stopped — max turns limit reached ({tool_calls}/{max_turns})]"
    result = truncate_response(collected, max_chars)

    meta = DelegateMeta(tool_calls=tool_calls, errors=error_count)
    total_tokens = input_tokens + output_tokens
    if total_tokens > 0:
        meta["usage"] = DelegateUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
    return result, meta
