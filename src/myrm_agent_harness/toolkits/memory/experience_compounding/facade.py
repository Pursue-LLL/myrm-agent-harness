"""Facade orchestrator for Experience Compounding and Knowledge Condensation Suite.

[POS]
Integrates frequency compounding, semantic condensation, active lease protection,
and cold tier annealing into a unified turnkey interface.

[INPUT]
- time, uuid
- .models, .compounding_engine, .condensation_engine, .annealing_governor

[OUTPUT]
- ExperienceCompoundingSuite
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.toolkits.memory.experience_compounding.annealing_governor import (
    ObsoleteContextAnnealingGovernor,
)
from myrm_agent_harness.toolkits.memory.experience_compounding.compounding_engine import (
    FrequencyCompoundingEngine,
)
from myrm_agent_harness.toolkits.memory.experience_compounding.condensation_engine import (
    KnowledgeCondensationEngine,
)
from myrm_agent_harness.toolkits.memory.experience_compounding.models import (
    AnnealingReport,
    CompoundedExperienceItem,
    CondensationReport,
    ExperienceItemState,
    GoldenRuleItem,
)


class ExperienceCompoundingSuite:
    """Turnkey facade managing compounding weights, Golden Rule synthesis, and annealing."""

    def __init__(
        self,
        compounding_engine: FrequencyCompoundingEngine | None = None,
        condensation_engine: KnowledgeCondensationEngine | None = None,
        annealing_governor: ObsoleteContextAnnealingGovernor | None = None,
    ) -> None:
        self._compounding = compounding_engine or FrequencyCompoundingEngine()
        self._condensation = condensation_engine or KnowledgeCondensationEngine()
        self._annealing = annealing_governor or ObsoleteContextAnnealingGovernor()

        self._items: dict[str, CompoundedExperienceItem] = {}
        self._rules: dict[str, GoldenRuleItem] = {}

    def add_item(
        self,
        content: str,
        topic: str,
        base_weight: float = 1.0,
        is_temporary: bool = False,
        is_pinned: bool = False,
        tags: list[str] | None = None,
        item_id: str | None = None,
    ) -> CompoundedExperienceItem:
        """Register a new experience item into the suite."""
        now = time.time()
        uid = item_id or f"exp-{uuid.uuid4().hex[:8]}"
        item = CompoundedExperienceItem(
            item_id=uid,
            content=content,
            topic=topic,
            base_weight=base_weight,
            compounded_weight=base_weight,
            last_adopted_at=now,
            created_at=now,
            is_temporary=is_temporary,
            is_pinned=is_pinned,
            tags=tags or [],
        )
        self._items[uid] = item
        return item

    def get_item(self, item_id: str) -> CompoundedExperienceItem | None:
        """Retrieve an experience item by ID."""
        return self._items.get(item_id)

    def reinforce(self, item_id: str, adopted: bool = True) -> float:
        """Reinforce item compounding weight following verification."""
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(f"Item not found: {item_id}")
        return self._compounding.reinforce(item, adopted=adopted)

    def condense(self) -> tuple[list[GoldenRuleItem], CondensationReport]:
        """Trigger semantic condensation of active fragments into Golden Rules."""
        active_list = [it for it in self._items.values() if it.is_active()]
        new_rules, report = self._condensation.condense(active_list)
        for r in new_rules:
            self._rules[r.rule_id] = r
        return new_rules, report

    def decondense(self, rule_id: str) -> list[CompoundedExperienceItem]:
        """Roll back a Golden Rule and reactivate its archived fragments."""
        rules_list = list(self._rules.values())
        fragments_list = list(self._items.values())
        reactivated = self._condensation.decondense(rule_id, rules_list, fragments_list)
        self._rules.pop(rule_id, None)
        return reactivated

    def anneal(self, current_time: float | None = None) -> AnnealingReport:
        """Apply exponential annealing decay to obsolete and temporary items."""
        return self._annealing.apply_annealing(
            list(self._items.values()), current_time=current_time
        )

    def list_golden_rules(self) -> list[GoldenRuleItem]:
        """Return all active Golden Rules."""
        return list(self._rules.values())

    def list_active_items(self) -> list[CompoundedExperienceItem]:
        """Return active un-condensed experience items."""
        return [it for it in self._items.values() if it.is_active()]

    def get_stats(self) -> dict[str, int | float]:
        """Return operational metrics across compounding, condensation, and cold tiers."""
        active_cnt = sum(1 for it in self._items.values() if it.is_active())
        condensed_cnt = sum(
            1 for it in self._items.values() if it.state == ExperienceItemState.CONDENSED_ARCHIVED
        )
        cold_cnt = sum(
            1 for it in self._items.values() if it.state == ExperienceItemState.COLD_TIERED
        )
        avg_weight = (
            sum(it.compounded_weight for it in self._items.values()) / float(len(self._items))
            if self._items
            else 0.0
        )
        return {
            "total_items": len(self._items),
            "active_items": active_cnt,
            "condensed_items": condensed_cnt,
            "cold_tiered_items": cold_cnt,
            "golden_rules_count": len(self._rules),
            "average_compounded_weight": round(avg_weight, 3),
        }
