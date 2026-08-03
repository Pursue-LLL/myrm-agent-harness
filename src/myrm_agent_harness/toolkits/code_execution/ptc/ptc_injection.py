"""PTC injection for sandbox Python execution (Dynamic Workflow only).

[INPUT]
- .rpc_server::PtcRpcServer (POS: Ephemeral RPC server)
- .dispatcher::PtcDispatcher (POS: Tool execution delegate)
- .stub_generator::generate_stubs (POS: myrm_tools.py codegen)
- .models::PtcConfig (POS: PTC configuration)
- toolkits.code_execution.ptc.context::ptc_nesting_guard (POS: PTC nesting guard ContextVar)
- toolkits.code_execution.executors.base::CodeExecutor, ExecutionContext (POS: Executor protocol)

[OUTPUT]
- inject_ptc_for_python_execution: Ephemeral RPC execution for an explicit allowed tool list (Dynamic Workflow).

[POS]
Bridges PTC RPC into sandbox Python execution for callers that pass an explicit
tool allowlist (Dynamic Workflow spawn/notify). Bash Turn1 does not call this path.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        CodeExecutor,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
        ExecutionResult,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.dispatcher import (
        PtcDispatcher,
    )

logger = logging.getLogger(__name__)

_PTC_NESTING_ERROR = (
    "Nested PTC execution is not allowed. Dynamic Workflow orchestration "
    "cannot start a second myrm_tools RPC session inside an active one."
)
_PTC_SERVER_START_ERROR = (
    "Dynamic Workflow PTC RPC server failed to start. Orchestration cannot "
    "execute myrm_tools.spawn_subagent / notify without an active RPC bridge."
)


async def inject_ptc_for_python_execution(
    context: ExecutionContext,
    executor: CodeExecutor,
    ptc_tools: list[BaseTool],
    override_allowed: frozenset[str] = frozenset(),
) -> ExecutionResult:
    """Execute Python with an explicit PTC tool allowlist inside the sandbox.

    Lifecycle:
    1. Reject nested PTC sessions via ``ptc_nesting_guard``
    2. Start ephemeral PtcRpcServer + PtcDispatcher with provided tools
    3. Generate myrm_tools.py stubs to a temp directory
    4. Inject _MYRM_PTC_SOCKET and PYTHONPATH into context.env
    5. Execute via CodeExecutor (sandbox, wrapper, timeout)
    6. Stop server and clean up
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult
    from myrm_agent_harness.toolkits.code_execution.ptc.context import (
        ptc_nesting_guard,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.dispatcher import (
        PtcDispatcher,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.models import PtcConfig
    from myrm_agent_harness.toolkits.code_execution.ptc.rpc_server import (
        PtcRpcServer,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.stub_generator import (
        generate_stubs,
    )

    if ptc_nesting_guard.get():
        logger.warning("Blocked nested PTC injection attempt")
        return ExecutionResult(
            success=False,
            stderr=_PTC_NESTING_ERROR,
            error=_PTC_NESTING_ERROR,
            error_category="guardrail_blocked",
            error_hint=_PTC_NESTING_ERROR,
        )

    config = PtcConfig(
        max_tool_calls=50,
        timeout_seconds=min(context.timeout or 300, 600),
    )
    dispatcher = PtcDispatcher(ptc_tools, override_allowed=override_allowed)
    server = PtcRpcServer(config, dispatcher)

    try:
        await server.start()
    except Exception as exc:
        logger.error("PTC server start failed (%s); refusing plain exec fallback", exc)
        return ExecutionResult(
            success=False,
            stderr=f"{_PTC_SERVER_START_ERROR} ({exc})",
            error=_PTC_SERVER_START_ERROR,
            error_category="execution_failure",
            error_hint=_PTC_SERVER_START_ERROR,
        )

    stub_dir: str | None = None
    token = ptc_nesting_guard.set(True)
    try:
        use_tcp = sys.platform == "win32"
        stub_source = generate_stubs(ptc_tools, use_tcp_fallback=use_tcp)

        stub_dir = tempfile.mkdtemp(prefix="myrm_ptc_stubs_")
        stub_path = Path(stub_dir) / "myrm_tools.py"
        stub_path.write_text(stub_source, encoding="utf-8")

        child_env = server.get_child_env()
        child_env["PYTHONPATH"] = stub_dir + os.pathsep + child_env.get("PYTHONPATH", "")

        patched_context = _patch_context_env(context, child_env)

        logger.info(
            "PTC injected for orchestration script: %d tools exposed, socket=%s",
            len(ptc_tools),
            server.socket_path or f"tcp:{server.tcp_port}",
        )

        result = await executor.execute(patched_context)

        if server.call_count > 0:
            logger.info("PTC session: %d tool calls dispatched", server.call_count)
            await _emit_ptc_trace(dispatcher, result.success)

        return result
    finally:
        ptc_nesting_guard.reset(token)
        await server.stop()
        if stub_dir:
            import shutil

            shutil.rmtree(stub_dir, ignore_errors=True)


async def _emit_ptc_trace(dispatcher: PtcDispatcher, script_success: bool | None) -> None:
    """Emit structured PTC execution trace to the observability layer."""
    records = dispatcher.records
    if not records:
        return

    total_ms = sum(r.duration_ms for r in records)
    failed = sum(1 for r in records if not r.success)

    try:
        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        await dispatch_custom_event(
            "ptc_trace",
            {
                "event": "ptc_trace",
                "tool_calls": len(records),
                "total_duration_ms": round(total_ms, 1),
                "failed_calls": failed,
                "script_success": script_success,
                "calls": [
                    {
                        "tool": r.tool,
                        "duration_ms": round(r.duration_ms, 1),
                        "success": r.success,
                    }
                    for r in records[:20]
                ],
            },
        )
    except Exception:
        pass


def _patch_context_env(context: ExecutionContext, extra_env: dict[str, str]) -> ExecutionContext:
    """Create a new ExecutionContext with additional env vars merged."""
    from dataclasses import replace

    merged_env: dict[str, str] = dict(context.env) if context.env else {}
    if "PYTHONPATH" in merged_env and "PYTHONPATH" in extra_env:
        extra_env["PYTHONPATH"] = extra_env["PYTHONPATH"] + os.pathsep + merged_env["PYTHONPATH"]
    merged_env.update(extra_env)

    return replace(context, env=merged_env)
