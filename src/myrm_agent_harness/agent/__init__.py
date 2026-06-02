"""Agent core module — public API."""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseAgent": ("myrm_agent_harness.agent.base_agent", "BaseAgent"),
    "SkillAgent": ("myrm_agent_harness.agent.skill_agent", "SkillAgent"),
    "create_skill_agent": ("myrm_agent_harness.agent.skill_agent_factory", "create_skill_agent"),
    "LLMConfig": ("myrm_agent_harness.agent.config", "LLMConfig"),
    "AgentRuntimeConfig": ("myrm_agent_harness.agent.types", "AgentRuntimeConfig"),
    "SubagentConfig": ("myrm_agent_harness.agent.types", "SubagentConfig"),
    "SUBAGENT_CONFIGS": ("myrm_agent_harness.agent.types", "SUBAGENT_CONFIGS"),
    "register_subagent_configs": ("myrm_agent_harness.agent.types", "register_subagent_configs"),
    "register_subagent_configs_from_directory": (
        "myrm_agent_harness.agent.types",
        "register_subagent_configs_from_directory",
    ),
    "auto_register_subagent_configs": ("myrm_agent_harness.agent.types", "auto_register_subagent_configs"),
    "SubAgentStatus": ("myrm_agent_harness.agent.types", "SubAgentStatus"),
    "SubAgentResult": ("myrm_agent_harness.agent.types", "SubAgentResult"),
    "HookEvent": ("myrm_agent_harness.agent.hooks", "HookEvent"),
    "HookRegistry": ("myrm_agent_harness.agent.hooks", "HookRegistry"),
    "HookExecutor": ("myrm_agent_harness.agent.hooks", "HookExecutor"),
    "fire_hook": ("myrm_agent_harness.agent.hooks", "fire_hook"),
    "AgentEventType": ("myrm_agent_harness.agent.types", "AgentEventType"),
    "AgentRunStatistics": ("myrm_agent_harness.agent.types", "AgentRunStatistics"),
    "CompletionStatus": ("myrm_agent_harness.agent.types", "CompletionStatus"),
    "map_to_completion_status": ("myrm_agent_harness.agent.types", "map_to_completion_status"),
    "TokenUsage": ("myrm_agent_harness.utils.token_economics.tracker", "TokenUsage"),
    "EventLogBackend": ("myrm_agent_harness.agent.event_log.protocols", "EventLogBackend"),
    "FileEventLogBackend": ("myrm_agent_harness.agent.event_log.backends.file_backend", "FileEventLogBackend"),
    "GracefulShutdownManager": ("myrm_agent_harness.agent.hooks.graceful_shutdown", "GracefulShutdownManager"),
    "get_shutdown_manager": ("myrm_agent_harness.agent.hooks.graceful_shutdown", "get_shutdown_manager"),
}

__all__ = [
    "SUBAGENT_CONFIGS",
    "AgentEventType",
    "AgentRunStatistics",
    "AgentRuntimeConfig",
    "BaseAgent",
    "CompletionStatus",
    "EventLogBackend",
    "FileEventLogBackend",
    "GracefulShutdownManager",
    "HookEvent",
    "HookExecutor",
    "HookRegistry",
    "LLMConfig",
    "SkillAgent",
    "SubAgentResult",
    "SubAgentStatus",
    "SubagentConfig",
    "TokenUsage",
    "auto_register_subagent_configs",
    "create_skill_agent",
    "fire_hook",
    "get_shutdown_manager",
    "map_to_completion_status",
    "register_subagent_configs",
    "register_subagent_configs_from_directory",
]


def __getattr__(name: str) -> object:
    """Lazily resolve public exports to keep agent package import lightweight."""
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
