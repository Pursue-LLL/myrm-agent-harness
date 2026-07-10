"""Public API surface for myrm-agent-harness.

External consumers (myrm-agent-server, third-party agent frameworks) should
import from ``myrm_agent_harness.api`` rather than reaching into internal
modules.  Core implementation may ship as compiled native extensions (``.so``)
in release wheels while this layer remains readable Python source.

Quick start::

    from myrm_agent_harness.api import create_skill_agent, LLMConfig

    agent = await create_skill_agent(llm_config=LLMConfig(...))
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AgentConfig",
    "AgentEventType",
    "AgentProfileBackend",
    "AgentRuntimeConfig",
    "AgentRuntimeSpec",
    "AgentStreamEvent",
    "build_parent_delegatable_toolkit",
    "CompletionStatus",
    "ConfigIncompleteError",
    "HookEvent",
    "HookRegistryProtocol",
    "IntegrationProvider",
    "KanbanStore",
    "LLMConfig",
    "SkillAgent",
    "SkillBackend",
    "create_skill_agent",
    "get_distribution_mode",
    "is_compiled_distribution",
    "track_background_task",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentConfig": ("myrm_agent_harness.api.config", "AgentConfig"),
    "AgentEventType": ("myrm_agent_harness.api.types", "AgentEventType"),
    "AgentRuntimeConfig": ("myrm_agent_harness.api.types", "AgentRuntimeConfig"),
    "AgentRuntimeSpec": ("myrm_agent_harness.api.types", "AgentRuntimeSpec"),
    "AgentStreamEvent": ("myrm_agent_harness.api.types", "AgentStreamEvent"),
    "build_parent_delegatable_toolkit": (
        "myrm_agent_harness.api.subagents",
        "build_parent_delegatable_toolkit",
    ),
    "CompletionStatus": ("myrm_agent_harness.api.types", "CompletionStatus"),
    "ConfigIncompleteError": ("myrm_agent_harness.api.config", "ConfigIncompleteError"),
    "AgentProfileBackend": ("myrm_agent_harness.api.protocols", "AgentProfileBackend"),
    "HookEvent": ("myrm_agent_harness.api.protocols", "HookEvent"),
    "HookRegistryProtocol": ("myrm_agent_harness.api.protocols", "HookRegistryProtocol"),
    "IntegrationProvider": ("myrm_agent_harness.api.protocols", "IntegrationProvider"),
    "KanbanStore": ("myrm_agent_harness.api.protocols", "KanbanStore"),
    "LLMConfig": ("myrm_agent_harness.api.config", "LLMConfig"),
    "SkillAgent": ("myrm_agent_harness.api.factory", "SkillAgent"),
    "SkillBackend": ("myrm_agent_harness.api.protocols", "SkillBackend"),
    "create_skill_agent": ("myrm_agent_harness.api.factory", "create_skill_agent"),
    "get_distribution_mode": ("myrm_agent_harness._distribution", "get_distribution_mode"),
    "is_compiled_distribution": ("myrm_agent_harness._distribution", "is_compiled_distribution"),
    "track_background_task": ("myrm_agent_harness.agent._skill_agent_context", "track_background_task"),
}


if __debug__:
    _lazy_set = set(_EXPORTS.keys())
    _all_set = set(__all__)
    _missing = _all_set - _lazy_set
    _extra = _lazy_set - _all_set
    if _missing or _extra:
        raise RuntimeError(f"api: __all__ and _EXPORTS mismatch: missing={_missing}, extra={_extra}")


def __getattr__(name: str) -> object:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
