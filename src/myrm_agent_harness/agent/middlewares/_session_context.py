"""Middleware session context — shared ContextVars for the middleware chain.

Provides per-request context (SecurityConfig, workspace root, session key,
user ID, EventLogger) that multiple middlewares consume. Centralizes these
ContextVars so they are not owned by any single middleware.

[INPUT]
- agent.security.terminal_error_registry::TerminalErrorRegistry (POS: Turn-scoped terminal error storage with persistence.)
- agent.security.types::PrivacyPolicy, SecurityConfig (POS: Foundation layer of the security type hierarchy.)
- agent.event_log.logger::EventLogger (POS: Integration façade. Async-buffered writes ensure zero impact on the event production hot path.)
- core.security.guards.privacy_tracker::set_privacy_policy (POS: Per-turn privacy state tracker. ContextVar-based privacy policy access.)

[OUTPUT]
- set_allowed_domains_map: Set the allowed domains map for the current async context.
- get_allowed_domains_map: Get the allowed domains map for the current async context.
- set_security_config: Set the active SecurityConfig for the current async context.
- get_security_config: Get the active SecurityConfig for the current async context.
- set_workspace_root: Set the workspace root for PathPolicy evaluation in the current async context.
- set_canary_token / get_canary_token: Session-scoped canary token for output-side injection detection.
- set_is_shadow_agent / reset_is_shadow_agent / get_is_shadow_agent: Background shadow-agent bulkhead flag.

[POS]
Middleware session context — shared ContextVars for the middleware chain.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.terminal_error_registry import TerminalErrorRegistry
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SecurityConfig

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.event_log.logger import EventLogger
    from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
    from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

_security_config_var: ContextVar[SecurityConfig | None] = ContextVar("security_config", default=None)
_workspace_root_var: ContextVar[str] = ContextVar("workspace_root", default="")
_pseudonym_store_var: ContextVar[PseudonymStore | None] = ContextVar("pseudonym_store", default=None)
_session_key_var: ContextVar[str] = ContextVar("approval_session_key", default="")
_agent_id_var: ContextVar[str] = ContextVar("agent_id", default="")
_user_id_var: ContextVar[str] = ContextVar("approval_user_id", default="")
_event_logger_var: ContextVar[EventLogger | None] = ContextVar("event_logger", default=None)
_allowed_domains_map_var: ContextVar[dict[str, list[str] | None] | None] = ContextVar(
    "allowed_domains_map", default=None
)
_is_subagent_var: ContextVar[bool] = ContextVar("is_subagent", default=False)
_subagent_task_id_var: ContextVar[str | None] = ContextVar("subagent_task_id", default=None)
_is_shadow_agent_var: ContextVar[bool] = ContextVar("is_shadow_agent", default=False)
_canary_token_var: ContextVar[str] = ContextVar("canary_token", default="")


def set_allowed_domains_map(domains_map: dict[str, list[str] | None]) -> None:
    """Set the allowed domains map for the current async context."""
    _allowed_domains_map_var.set(domains_map)


def get_allowed_domains_map() -> dict[str, list[str] | None]:
    """Get the allowed domains map for the current async context."""
    val = _allowed_domains_map_var.get()
    return val if val is not None else {}


def set_security_config(config: SecurityConfig | None) -> None:
    """Set the active SecurityConfig for the current async context."""
    _security_config_var.set(config)
    from myrm_agent_harness.core.security.guards.privacy_tracker import (
        set_privacy_policy,
    )

    set_privacy_policy(config.privacy_policy if config else None)


def get_security_config() -> SecurityConfig | None:
    """Get the active SecurityConfig for the current async context."""
    return _security_config_var.get()


def set_workspace_root(path: str) -> None:
    """Set the workspace root for PathPolicy evaluation in the current async context."""
    _workspace_root_var.set(path)


def get_workspace_root() -> str:
    """Get the workspace root for the current async context."""
    return _workspace_root_var.get()


def set_approval_session(session_key: str) -> None:
    """Set the session key for approval routing."""
    _session_key_var.set(session_key)


def get_approval_session() -> str:
    """Get the session key for the current async context."""
    return _session_key_var.get()


def set_agent_id(agent_id: str) -> None:
    """Set the agent ID for the current async context."""
    _agent_id_var.set(agent_id)


def get_agent_id() -> str:
    """Get the agent ID for the current async context."""
    return _agent_id_var.get()


def set_approval_user_id(user_id: str) -> None:
    """Set the user ID for allowlist lookups in the current async context."""
    _user_id_var.set(user_id)


def get_approval_user_id() -> str:
    """Get the user ID for the current async context."""
    return _user_id_var.get()


def get_privacy_policy() -> PrivacyPolicy:
    """Get the active PrivacyPolicy from SecurityConfig.

    Delegates to core.security.guards.privacy_tracker.get_privacy_policy()
    which uses its own ContextVar, kept in sync by set_security_config().
    """
    from myrm_agent_harness.core.security.guards.privacy_tracker import (
        get_privacy_policy as _core_get_privacy_policy,
    )

    return _core_get_privacy_policy()


def set_pseudonym_store(store: PseudonymStore | None) -> None:
    """Set the PseudonymStore for the current async context."""
    _pseudonym_store_var.set(store)


def get_pseudonym_store() -> PseudonymStore | None:
    """Get the PseudonymStore for the current async context.

    Returns None if pseudonymization is not configured.
    """
    return _pseudonym_store_var.get()


def set_event_logger(logger: EventLogger | None) -> None:
    """Set the EventLogger for the current async context."""
    _event_logger_var.set(logger)


def get_event_logger() -> EventLogger | None:
    """Get the EventLogger for the current async context."""
    return _event_logger_var.get()


_terminal_errors_var: ContextVar[TerminalErrorRegistry] = ContextVar("terminal_errors")


def get_terminal_errors() -> TerminalErrorRegistry:
    """Get the registry of terminal error categories (e.g. 'network_blocked') detected in the current turn."""
    try:
        return _terminal_errors_var.get()
    except LookupError:
        registry = TerminalErrorRegistry()
        _terminal_errors_var.set(registry)
        return registry


def reset_terminal_errors() -> None:
    """Reset the set of terminal errors for the current async context."""
    try:
        registry = _terminal_errors_var.get()
        registry.clear()
    except LookupError:
        registry = TerminalErrorRegistry()
        registry.clear()
        _terminal_errors_var.set(registry)


_active_tool_registry_var: ContextVar[ToolRegistry | None] = ContextVar("active_tool_registry", default=None)
_active_resolved_tools_var: ContextVar[list[BaseTool] | None] = ContextVar("active_resolved_tools", default=None)


def set_active_tool_registry(registry: ToolRegistry) -> None:
    """Publish the agent's ToolRegistry for dynamic tool resolution during execution."""
    _active_tool_registry_var.set(registry)


def get_active_tool_registry() -> ToolRegistry | None:
    """Return the ToolRegistry for the current agent run, if set."""
    return _active_tool_registry_var.get()


def set_active_resolved_tools(tools: list[BaseTool]) -> None:
    """Publish the resolved tool instances bound to the current agent graph."""
    _active_resolved_tools_var.set(tools)


def get_active_resolved_tools() -> list[BaseTool] | None:
    """Return resolved tools for the current agent run, if set."""
    return _active_resolved_tools_var.get()


def set_is_subagent(is_subagent: bool) -> None:
    """Mark the current execution context as a subagent.

    This is critical for preventing autonomous subagents from triggering
    UI-based approval flows that would cause deadlocks.
    """
    _is_subagent_var.set(is_subagent)


def get_is_subagent() -> bool:
    """Check if the current execution context is a subagent.

    Returns:
        True if running in a subagent context, False otherwise.
    """
    return _is_subagent_var.get()


def set_subagent_task_id(task_id: str | None) -> None:
    """Set the task ID for the current subagent context."""
    _subagent_task_id_var.set(task_id)


def get_subagent_task_id() -> str | None:
    """Get the task ID for the current subagent context.

    Returns:
        The subagent task ID, or None if not in a subagent context.
    """
    return _subagent_task_id_var.get()


def set_is_shadow_agent(is_shadow: bool) -> Token[bool]:
    """Mark the current execution context as a background shadow agent."""
    return _is_shadow_agent_var.set(is_shadow)


def reset_is_shadow_agent(token: Token[bool]) -> None:
    """Restore the previous shadow-agent flag."""
    _is_shadow_agent_var.reset(token)


def get_is_shadow_agent() -> bool:
    """Return True when running inside a shadow-agent bulkhead context."""
    return _is_shadow_agent_var.get()


def set_canary_token(token: str) -> None:
    """Set the canary token for the current session."""
    _canary_token_var.set(token)


def get_canary_token() -> str:
    """Get the canary token for the current session.

    Returns empty string if no canary has been set.
    """
    return _canary_token_var.get()
