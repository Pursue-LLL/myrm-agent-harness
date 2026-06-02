"""In-memory AutomationStore implementation.

Used for testing and as a reference for persistence adapters.

[INPUT]
- .types::AutomationRule (POS: Automation domain types.)
- .protocols::AutomationStore (POS: Protocols for the automation toolkit.)

[OUTPUT]
- InMemoryAutomationStore: Non-persistent reference implementation.

[POS]
In-memory AutomationStore implementation.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.automation.protocols import AutomationStore
from myrm_agent_harness.toolkits.automation.types import (
    AutomationRule,
    AutomationRuleStatus,
)


class InMemoryAutomationStore(AutomationStore):
    """Non-persistent reference implementation.

    Thread-safety: not guaranteed — intended for single-process tests.
    Production deployments must use a database-backed implementation.
    """

    def __init__(self) -> None:
        self._rules: dict[str, AutomationRule] = {}

    async def get_rule(self, rule_id: str) -> AutomationRule | None:
        rule = self._rules.get(rule_id)
        return copy.deepcopy(rule) if rule else None

    async def list_rules(
        self,
        *,
        status: AutomationRuleStatus | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AutomationRule]:
        results = list(self._rules.values())
        if status is not None:
            results = [r for r in results if r.status == status]
        if agent_id is not None:
            results = [r for r in results if r.agent_id == agent_id]
        if enabled is not None:
            results = [r for r in results if r.enabled == enabled]
        results.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC))
        results = results[offset:]
        if limit is not None:
            results = results[:limit]
        return [copy.deepcopy(r) for r in results]

    async def count_rules(
        self,
        *,
        status: AutomationRuleStatus | None = None,
        agent_id: str | None = None,
        enabled: bool | None = None,
    ) -> int:
        count = 0
        for r in self._rules.values():
            if status is not None and r.status != status:
                continue
            if agent_id is not None and r.agent_id != agent_id:
                continue
            if enabled is not None and r.enabled != enabled:
                continue
            count += 1
        return count

    async def save_rule(self, rule: AutomationRule) -> AutomationRule:
        rule.updated_at = datetime.now(UTC)
        if rule.created_at is None:
            rule.created_at = datetime.now(UTC)
        self._rules[rule.rule_id] = copy.deepcopy(rule)
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        del self._rules[rule_id]
        return True
