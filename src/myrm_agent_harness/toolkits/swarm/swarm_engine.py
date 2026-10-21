"""[INPUT]
- models: SwarmModeConfig, SwarmSubagentTask, RecalledRuleItem, OwnerRiskItem, RiskSeverityLevel

[OUTPUT]
- SwarmCoordinationEngine: Core engine managing swarm execution, recalled rules and owner risk verification

[POS]
Harness framework engine for Swarm Coordination, Memory Recall HUD & Owner Risk Checklist (Item 42 P0).
Strictly under 160 lines. Zero `Any`.
"""

from __future__ import annotations

import threading

from .models import (
    OwnerRiskItem,
    RecalledRuleItem,
    SwarmModeConfig,
    SwarmSubagentTask,
)


class SwarmCoordinationEngine:
    """Thread-safe engine governing swarm task distribution, recalled rule enforcement, and owner risk checks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._configs: dict[str, SwarmModeConfig] = {}
        self._subagent_tasks: dict[str, list[SwarmSubagentTask]] = {}
        self._recalled_rules: dict[str, list[RecalledRuleItem]] = {}
        self._owner_risks: dict[str, list[OwnerRiskItem]] = {}

    def get_config(self, session_id: str) -> SwarmModeConfig:
        with self._lock:
            if session_id not in self._configs:
                self._configs[session_id] = SwarmModeConfig(session_id=session_id)
            return self._configs[session_id]

    def set_config(self, session_id: str, enabled: bool, concurrency_quota: int = 5) -> SwarmModeConfig:
        with self._lock:
            config = SwarmModeConfig(
                session_id=session_id,
                enabled=enabled,
                concurrency_quota=max(1, min(10, concurrency_quota)),
                auto_decompose=True,
            )
            self._configs[session_id] = config
            return config

    def assign_tasks(self, session_id: str, tasks: list[SwarmSubagentTask]) -> list[SwarmSubagentTask]:
        with self._lock:
            self._subagent_tasks[session_id] = list(tasks)
            return list(self._subagent_tasks[session_id])

    def get_tasks(self, session_id: str) -> list[SwarmSubagentTask]:
        with self._lock:
            return list(self._subagent_tasks.get(session_id, []))

    def record_recalled_rules(self, session_id: str, rules: list[RecalledRuleItem]) -> list[RecalledRuleItem]:
        with self._lock:
            existing = self._recalled_rules.setdefault(session_id, [])
            for r in rules:
                # Deduplicate by rule_id
                if not any(item.rule_id == r.rule_id for item in existing):
                    existing.append(r)
            return list(existing)

    def get_recalled_rules(self, session_id: str) -> list[RecalledRuleItem]:
        with self._lock:
            return list(self._recalled_rules.get(session_id, []))

    def toggle_rule_active(self, session_id: str, rule_id: str, is_active: bool) -> RecalledRuleItem | None:
        with self._lock:
            rules = self._recalled_rules.get(session_id, [])
            for r in rules:
                if r.rule_id == rule_id:
                    r.is_active = is_active
                    return r
            return None

    def compile_active_rules_prompt(self, session_id: str) -> str:
        with self._lock:
            rules = self._recalled_rules.get(session_id, [])
            active_rules = [r for r in rules if r.is_active]

        if not active_rules:
            return ""

        lines = [
            "### [@active_rules: Verified Memory & Business Guidelines]",
            f"The following {len(active_rules)} business rules were recalled from previous user turns:",
        ]
        for r in active_rules:
            lines.append(f"- [{r.category}] {r.summary} (confidence: {r.confidence:.2f})")
        lines.append("\nINSTRUCTION: Strictly uphold these business rules in all current plans and deliverables.")
        return "\n".join(lines)

    def register_risks(self, session_id: str, risks: list[OwnerRiskItem]) -> list[OwnerRiskItem]:
        with self._lock:
            existing = self._owner_risks.setdefault(session_id, [])
            for item in risks:
                if not any(e.risk_id == item.risk_id for e in existing):
                    existing.append(item)
            return list(existing)

    def get_risks(self, session_id: str) -> list[OwnerRiskItem]:
        with self._lock:
            return list(self._owner_risks.get(session_id, []))

    def set_risk_confirmation(
        self, session_id: str, risk_id: str, is_confirmed: bool, confirmed_by: str = ""
    ) -> OwnerRiskItem | None:
        with self._lock:
            risks = self._owner_risks.get(session_id, [])
            for r in risks:
                if r.risk_id == risk_id:
                    r.is_confirmed = is_confirmed
                    r.confirmed_by = confirmed_by if is_confirmed else ""
                    return r
            return None
