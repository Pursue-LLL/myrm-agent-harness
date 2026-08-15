"""LangChain ``StructuredTool`` subclass whose callable receives every argument.

``langchain_core`` ``StructuredTool._run``/``_arun`` declare ``config`` (and
``run_manager``) as keyword-only parameters. When a tool argument is named
``config`` (a common parameter name in third-party MCP servers and REST APIs),
``run``/``arun`` bind the user-supplied value into that slot instead of
``**kwargs``, silently dropping it from the dispatched payload — the MCP server
then rejects the call with ``Field required``. Overriding both ``_run`` and
``_arun`` to accept only ``*args``/``**kwargs`` keeps every argument inside
``kwargs`` forwarded to the callable. The overridden signatures no longer
advertise ``run_manager`` or a ``RunnableConfig`` parameter, so ``run``/``arun``
inject neither, preserving current behavior for all other argument names.

[INPUT]
- langchain_core.tools::StructuredTool (POS: LangChain tool base class)

[OUTPUT]
- SafeStructuredTool: StructuredTool subclass with reserved-name-safe ``_run``/``_arun``

[POS]
MCP/OpenAPI tool construction. Framework-level fix for the langchain-core
``config``/``run_manager`` parameter-name collision.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool


class SafeStructuredTool(StructuredTool):
    """``StructuredTool`` whose ``_run``/``_arun`` never swallow ``config``/``run_manager`` args."""

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        if self.func:
            return self.func(*args, **kwargs)
        msg = "StructuredTool does not support sync invocation."
        raise NotImplementedError(msg)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        if self.coroutine:
            return await self.coroutine(*args, **kwargs)
        return await super()._arun(*args, **kwargs)
