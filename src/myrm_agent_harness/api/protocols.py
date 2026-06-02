"""Public Protocol definitions for framework extension points.

Implement these protocols in your application layer to plug custom backends
into the harness without modifying core engine code.
"""

from __future__ import annotations

from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.extensions.protocols import AgentExtension
from myrm_agent_harness.backends.profiles.protocols import AgentProfileBackend
from myrm_agent_harness.backends.secrets.protocols import AgentSecretBackend
from myrm_agent_harness.backends.skills.protocols import SkillBackend
from myrm_agent_harness.core.hooks.types import HookEvent, HookRegistryProtocol, HookResult
from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore
from myrm_agent_harness.toolkits.memory.integration.protocols import IntegrationProvider

__all__ = [
    "AgentExtension",
    "AgentProfileBackend",
    "AgentSecretBackend",
    "EventLogBackend",
    "HookEvent",
    "HookRegistryProtocol",
    "HookResult",
    "IntegrationProvider",
    "KanbanStore",
    "SkillBackend",
]
