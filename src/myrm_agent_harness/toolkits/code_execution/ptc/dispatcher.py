"""PTC request dispatcher.

[INPUT]
- .models::PtcRpcRequest, PtcRpcResponse, PtcToolCallRecord (POS: RPC protocol)
- .security::TERMINAL_BLOCKED_PARAMS (POS: Security constraints)
- langchain_core.tools::BaseTool (POS: Tool execution interface)

[OUTPUT]
- PtcDispatcher: Maps RPC requests to tool executions via middleware chain

[POS]
Bridges PTC RPC requests to the agent tool system. Resolves tool by name,
applies security guards (terminal param blocking, tool call budget),
invokes the tool, and records execution trace data.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.ptc.models import (
    PtcRpcRequest,
    PtcRpcResponse,
    PtcToolCallRecord,
)
from myrm_agent_harness.toolkits.code_execution.ptc.security import (
    TERMINAL_BLOCKED_PARAMS,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_BLOCKED_TOOLS: frozenset[str] = frozenset(
    {"execute_code", "execute_python", "bash_code_execute_tool", "spawn_subagent"}
)


class PtcDispatcher:
    """Dispatches PTC RPC requests to agent tools.

    Maintains a name->tool mapping and records call traces for observability.
    """

    def __init__(
        self,
        tools: list[BaseTool],
        override_allowed: frozenset[str] = frozenset(),
    ) -> None:
        self._tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools}
        self._override_allowed = override_allowed
        self._records: list[PtcToolCallRecord] = []

    @property
    def tools(self) -> list[BaseTool]:
        """List of tools available for dispatch."""
        return list(self._tools_by_name.values())

    @property
    def records(self) -> list[PtcToolCallRecord]:
        """Collected tool call records for the execution trace."""
        return self._records

    async def dispatch(self, request: PtcRpcRequest) -> PtcRpcResponse:
        """Dispatch a single tool-call request and return the response."""
        start = time.perf_counter()
        tool_name = request.tool

        if tool_name in _BLOCKED_TOOLS and tool_name not in self._override_allowed:
            return self._record_error(
                tool_name, request.args, start, f"Tool '{tool_name}' is not callable from PTC scripts"
            )

        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            return self._record_error(tool_name, request.args, start, f"Unknown tool: '{tool_name}'")

        args = dict(request.args)

        if tool_name in ("terminal", "bash") and TERMINAL_BLOCKED_PARAMS:
            for blocked in TERMINAL_BLOCKED_PARAMS:
                args.pop(blocked, None)

        try:
            result = await tool.ainvoke(input=args)

            if isinstance(result, str):
                result_str = result
            elif hasattr(result, "content"):
                result_str = str(result.content)
            else:
                result_str = json.dumps(result, ensure_ascii=False, default=str)

            duration_ms = (time.perf_counter() - start) * 1000
            self._records.append(
                PtcToolCallRecord(
                    tool=tool_name,
                    args_preview=self._preview_args(args),
                    duration_ms=duration_ms,
                    success=True,
                )
            )
            return PtcRpcResponse(result=result_str)

        except Exception as e:
            return self._record_error(tool_name, args, start, str(e))

    def _record_error(
        self,
        tool_name: str,
        args: dict[str, object],
        start: float,
        error: str,
    ) -> PtcRpcResponse:
        """Record a failed call and return an error response."""
        duration_ms = (time.perf_counter() - start) * 1000
        self._records.append(
            PtcToolCallRecord(
                tool=tool_name,
                args_preview=self._preview_args(args),
                duration_ms=duration_ms,
                success=False,
                error=error[:200],
            )
        )
        return PtcRpcResponse(error=error)

    @staticmethod
    def _preview_args(args: dict[str, object]) -> str:
        """Generate a compact preview of tool arguments."""
        preview = json.dumps(args, ensure_ascii=False, default=str)
        if len(preview) > 120:
            return preview[:117] + "..."
        return preview
