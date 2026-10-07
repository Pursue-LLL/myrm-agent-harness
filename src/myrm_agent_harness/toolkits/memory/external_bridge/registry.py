# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/registry.py
# [INPUT] models.py (ExternalAgentType), targets.py (BaseExternalAgentTarget)
# [OUTPUT] ExternalAgentTargetRegistry

"""Registry for external agent bridge targets.

Allows pluggable registration and resolution of bridge target adapters for
Cursor, Claude Code, Codex, Hermes, OpenClaw, and custom extensions.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.external_bridge.models import ExternalAgentType
from myrm_agent_harness.toolkits.memory.external_bridge.targets import (
    BaseExternalAgentTarget,
    ClaudeCodeBridgeTarget,
    CodexBridgeTarget,
    CursorBridgeTarget,
    HermesBridgeTarget,
    OpenClawBridgeTarget,
)


class ExternalAgentTargetRegistry:
    """Registry mapping agent types to their corresponding target adapter instances."""

    def __init__(self) -> None:
        self._targets: dict[ExternalAgentType, BaseExternalAgentTarget] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default out-of-the-box bridge target adapters."""
        self.register(CursorBridgeTarget())
        self.register(ClaudeCodeBridgeTarget())
        self.register(CodexBridgeTarget())
        self.register(HermesBridgeTarget())
        self.register(OpenClawBridgeTarget())

    def register(self, target: BaseExternalAgentTarget) -> None:
        """Register a bridge target adapter."""
        self._targets[target.agent_type] = target

    def get(self, agent_type: ExternalAgentType) -> BaseExternalAgentTarget:
        """Retrieve target adapter for given agent type, raising KeyError if missing."""
        if agent_type not in self._targets:
            raise KeyError(f"No target adapter registered for agent type: {agent_type}")
        return self._targets[agent_type]

    def list_supported_agents(self) -> list[ExternalAgentType]:
        """Return list of all registered agent types."""
        return list(self._targets.keys())
