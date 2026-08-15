"""LangChain ``StructuredTool`` subclass whose coroutine receives every argument.

``langchain_core`` ``BaseTool._arun`` declares ``config`` (and ``run_manager``)
as keyword-only parameters. When a tool argument is named ``config`` (a common
parameter name in third-party MCP servers and REST APIs), ``arun`` binds the
user-supplied value into the ``_arun`` positional slot instead of ``**kwargs``,
silently dropping it from the dispatched payload — the MCP server then rejects
the call with ``Field required``. Overriding ``_arun`` to accept only
``*args``/``**kwargs`` keeps every argument inside ``kwargs`` forwarded to the
coroutine. The overridden signature no longer advertises ``run_manager`` or a
``RunnableConfig`` parameter, so ``arun`` injects neither, preserving current
behavior for all other argument names.

[INPUT]
- langchain_core.tools::StructuredTool (POS: LangChain tool base class)

[OUTPUT]
- SafeStructuredTool: StructuredTool subclass with a reserved-name-safe ``_arun``

[POS]
MCP/OpenAPI tool construction. Framework-level fix for the langchain-core
``config``/``run_manager`` parameter-name collision.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool


class SafeStructuredTool(StructuredTool):
    """``StructuredTool`` whose ``_arun`` never swallows ``config``/``run_manager`` args."""

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        if self.coroutine:
            return await self.coroutine(*args, **kwargs)
        return await super()._arun(*args, **kwargs)
