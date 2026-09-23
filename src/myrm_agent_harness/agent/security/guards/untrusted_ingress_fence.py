"""Untrusted Ingress Fence — runtime tool privilege stripping for external inbound messages.

When an Agent session processes untrusted external messages (e.g., A2A tasks from
external peers, webhook triggers, public bot mentions), this fence strips high-privilege
destructive tools (Bash code execution, arbitrary workspace file writing) from the
active tool exposure surface, restricting the Agent to read-only exploration and scoped artifacts.

[INPUT]
- Tool names or tool instances from ToolRegistry / Agent runtime
- External ingress activation flag

[OUTPUT]
- is_untrusted_ingress_active(): ContextVar check
- set_untrusted_ingress() / reset_untrusted_ingress(): ContextVar mutators
- is_tool_allowed_under_untrusted_ingress(): Single tool authorization check
- filter_untrusted_ingress_tools(): Tool list filtering for LLM tool binding

[POS]
Layer 2 runtime security guard. Sits between Inbound Task Ingress and Agent Tool Registry.
Enforces physical least-privilege tool stripping to prevent prompt-injection attacks
from executing arbitrary system commands or destroying user workspace source code.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Tools strictly disallowed when handling untrusted external inputs.
# These tools possess destructive host privileges (arbitrary shell, file mutation).
DISALLOWED_UNTRUSTED_TOOLS: frozenset[str] = frozenset(
    {
        "bash_code_execute_tool",
        "shell_exec",
        "file_write_tool",
        "file_edit_tool",
    }
)

_untrusted_ingress_var: ContextVar[bool] = ContextVar("untrusted_ingress_active", default=False)


def is_untrusted_ingress_active() -> bool:
    """Check if the current async execution context is marked as untrusted ingress."""
    return _untrusted_ingress_var.get()


def set_untrusted_ingress(active: bool = True) -> None:
    """Set the untrusted ingress status for the current async execution context."""
    _untrusted_ingress_var.set(active)
    if active:
        logger.warning("[INGRESS_FENCE] Untrusted ingress context activated. Destructive tools stripped.")


def reset_untrusted_ingress() -> None:
    """Reset the untrusted ingress status for the current async execution context."""
    _untrusted_ingress_var.set(False)


def is_tool_allowed_under_untrusted_ingress(tool_name: str) -> bool:
    """Check whether a specific tool is permitted under an untrusted ingress session.

    Returns False if the tool is in DISALLOWED_UNTRUSTED_TOOLS.
    """
    clean_name = tool_name.strip().lower()
    return clean_name not in DISALLOWED_UNTRUSTED_TOOLS


def filter_untrusted_ingress_tools(tool_names: Iterable[str]) -> list[str]:
    """Filter an iterable of tool names, stripping destructive privileges if untrusted.

    If untrusted ingress is NOT active, returns all tool names unchanged.
    If untrusted ingress IS active, filters out any tool present in DISALLOWED_UNTRUSTED_TOOLS.
    """
    if not is_untrusted_ingress_active():
        return list(tool_names)

    allowed: list[str] = []
    stripped: list[str] = []
    for name in tool_names:
        if is_tool_allowed_under_untrusted_ingress(name):
            allowed.append(name)
        else:
            stripped.append(name)

    if stripped:
        logger.info(
            "[INGRESS_FENCE] Stripped %d high-privilege tools: %s",
            len(stripped),
            ", ".join(stripped),
        )

    return allowed
