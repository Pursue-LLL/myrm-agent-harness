"""Pre-sniffing guard against historical pitfalls and minefields.

[INPUT]
- Execution plan texts, candidate target entities, and CausalFlywheelStore.

[OUTPUT]
- MinefieldPreSniffingGuard: intercepts high-risk entities and formats proactive warnings.

[POS]
- Proactive guard against repeat pitfalls for Item 154 ProjectExperienceAndADRFlywheelSuite.
"""

from __future__ import annotations

from .flywheel_store import CausalFlywheelStore
from .models import ExperienceKind, MinefieldAlert


class MinefieldPreSniffingGuard:
    """Proactively sniffs plans and entity targets against historical bug experiences and conventions."""

    def __init__(self, flywheel_store: CausalFlywheelStore) -> None:
        self.flywheel_store = flywheel_store

    def sniff(
        self,
        plan_text: str,
        explicit_entities: list[str] | None = None,
    ) -> list[MinefieldAlert]:
        """Sniff plan text and candidate entities against historical experiences."""
        alerts: list[MinefieldAlert] = []
        seen_exp_ids: set[str] = set()

        entities_to_check: set[str] = set()
        if explicit_entities:
            entities_to_check.update(e.strip().lower() for e in explicit_entities if e.strip())

        # Scan plan text for known entities in flywheel
        lower_plan = plan_text.lower()
        all_experiences = self.flywheel_store.list_all()

        for exp in all_experiences:
            entity_lower = exp.target_entity.lower()
            if entity_lower in entities_to_check or entity_lower in lower_plan:
                if exp.experience_id in seen_exp_ids:
                    continue
                seen_exp_ids.add(exp.experience_id)

                severity = "critical" if exp.kind == ExperienceKind.BUG_EXPERIENCE else "warning"
                prefix = "⚡️ 历史雷区提醒" if exp.kind == ExperienceKind.BUG_EXPERIENCE else "📐 既定架构决策"

                msg = (
                    f"{prefix}：实体 [{exp.target_entity}] 存在历史记录 [{exp.experience_id}]。"
                    f" 触发条件: {exp.trigger_condition}。根因: {exp.root_cause_or_rationale}。"
                )

                alerts.append(
                    MinefieldAlert(
                        entity_matched=exp.target_entity,
                        experience_id=exp.experience_id,
                        kind=exp.kind,
                        warning_message=msg,
                        convention_to_follow=exp.convention_or_remedy,
                        severity=severity,
                    )
                )

        return alerts

    def format_alerts_prompt(self, alerts: list[MinefieldAlert]) -> str:
        """Format surfaced alerts into system prompt instructions."""
        if not alerts:
            return ""

        lines: list[str] = [
            "### [HISTORICAL MINEFIELD & ADR PRE-SNIFFING ADVISORY]",
            "The following rules were learned from past verified mistakes or technical decisions:",
        ]
        for a in alerts:
            lines.append(f"- **[{a.entity_matched}]** {a.warning_message}")
            lines.append(f"  👉 必须遵循约定: {a.convention_to_follow}")

        return "\n".join(lines)
