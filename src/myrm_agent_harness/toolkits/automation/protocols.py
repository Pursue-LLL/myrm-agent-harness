"""Protocols for the automation toolkit.

Defines the persistence contract that the application layer must satisfy.

[INPUT]
- .types::AutomationRule (POS: Automation domain types.)

[OUTPUT]
- AutomationStore: Persistence contract for automation rules.

[POS]
Protocols for the automation toolkit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.automation.types import (
        AutomationRule,
        AutomationRuleStatus,
    )


@runtime_checkable
class AutomationStore(Protocol):
    """Persistence contract for automation rules.

    All datetime values are UTC. Authorization is handled by the
    service layer — the store itself is auth-agnostic.
    """

    async def get_rule(self, rule_id: str) -> AutomationRule | None:
        """Return a rule by ID, or None."""
        ...

    async def list_rules(
        self,
        *,
        status: AutomationRuleStatus | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AutomationRule]:
        """Return rules with optional filters."""
        ...

    async def count_rules(
        self,
        *,
        status: AutomationRuleStatus | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
    ) -> int:
        """Count rules matching filters."""
        ...

    async def save_rule(self, rule: AutomationRule) -> AutomationRule:
        """Create or update a rule (upsert)."""
        ...

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule. Returns True if deleted."""
        ...
