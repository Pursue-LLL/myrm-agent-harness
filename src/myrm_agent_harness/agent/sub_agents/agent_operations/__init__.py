"""[INPUT] None.
[OUTPUT] Facade exports for agent-owned operations fabric.
[POS] Public API package root for agent_operations.
"""

from .fabric import AgentOwnedOperationsFabric
from .types import (
    AgentOwnedExecutionContext,
    AgentProviderConfig,
    AgentRosterEntry,
    AgentScopedError,
)

__all__ = [
    "AgentOwnedOperationsFabric",
    "AgentOwnedExecutionContext",
    "AgentProviderConfig",
    "AgentRosterEntry",
    "AgentScopedError",
]
