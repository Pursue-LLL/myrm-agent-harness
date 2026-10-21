"""
[INPUT]: Skill identifier strings, ContextVar token instances.
[OUTPUT]: Async/thread-safe ContextVar manager propagating the currently active skill across span lifecycles.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/active_skill_telemetry/context.py
"""

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator, Optional

_active_skill_var: ContextVar[Optional[str]] = ContextVar("myrm_active_skill", default=None)


def get_active_skill() -> Optional[str]:
    """Retrieve the currently active skill bound to the local execution context."""
    return _active_skill_var.get()


def set_active_skill(skill_name: Optional[str]) -> Token[Optional[str]]:
    """Bind a skill as currently active. Returns token for reset."""
    return _active_skill_var.set(skill_name)


def reset_active_skill(token: Token[Optional[str]]) -> None:
    """Restore the previous active skill binding using token."""
    _active_skill_var.reset(token)


@contextmanager
def bind_active_skill(skill_name: str) -> Generator[str, None, None]:
    """Context manager binding an active skill for a block and guaranteeing clean restoration."""
    token = set_active_skill(skill_name)
    try:
        yield skill_name
    finally:
        reset_active_skill(token)
