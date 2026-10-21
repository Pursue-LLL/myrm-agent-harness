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

from langchain_core.messages import ToolMessage
from pydantic import BaseModel

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


def _unwrap_tool_message(value: object) -> object:
    """Reduce a LangChain ToolMessage to its payload.

    ``response_format="content_and_artifact"`` tools put the structured result in
    ``artifact``; plain tools put it in ``content``. Preferring ``artifact`` keeps
    structured payloads intact instead of degrading them to a text blob.
    """
    if not isinstance(value, ToolMessage):
        return value
    artifact = getattr(value, "artifact", None)
    return artifact if artifact is not None else value.content


def _to_json_native(value: object) -> object:
    """Normalize a tool result into a JSON-native payload for the RPC envelope.

    Scripts consume these values directly, so structure is preserved: dicts and
    lists survive as-is, scalars stay scalars. Anything else (dataclasses, Pydantic
    models, datetimes, custom objects) is reduced through ``json.dumps(default=str)``
    so the child process never receives an unserializable object.
    """
    unwrapped = _unwrap_tool_message(value)
    if unwrapped is None or isinstance(unwrapped, str | int | float | bool):
        return unwrapped
    if isinstance(unwrapped, dict | list):
        try:
            json.dumps(unwrapped)
        except (TypeError, ValueError):
            return json.loads(json.dumps(unwrapped, ensure_ascii=False, default=str))
        return unwrapped
    if isinstance(unwrapped, BaseModel):
        return unwrapped.model_dump(mode="json")
    return json.loads(json.dumps(unwrapped, ensure_ascii=False, default=str))


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
            payload = _to_json_native(result)

            duration_ms = (time.perf_counter() - start) * 1000
            self._records.append(
                PtcToolCallRecord(
                    tool=tool_name,
                    args_preview=self._preview_args(args),
                    duration_ms=duration_ms,
                    success=True,
                )
            )
            return PtcRpcResponse(result=payload)

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
