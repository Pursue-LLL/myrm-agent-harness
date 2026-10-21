"""PTC execution context flags shared between bash executor and PTC injection.

[INPUT]
- contextvars::ContextVar (POS: coroutine-safe nesting guard)

[OUTPUT]
- ptc_nesting_guard: ContextVar[bool] — True while a PTC child process is active

[POS]
Prevents nested PTC server startup when PTC scripts invoke bash with Python code.
"""

from __future__ import annotations

from contextvars import ContextVar

ptc_nesting_guard: ContextVar[bool] = ContextVar("ptc_nesting_guard", default=False)

__all__ = ["ptc_nesting_guard"]
