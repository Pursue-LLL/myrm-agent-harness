"""[POS]: src/myrm_agent_harness/toolkits/memory/job_compounding/compounding_engine.py
[INPUT]: Feedback cues, correction lessons, agent directories, and rule types.
[OUTPUT]: PreferenceCompoundingEngine persisting compounded rules and syncing to MEMORY.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .models import CompoundedRule, RuleType


class PreferenceCompoundingEngine:
    """Extracts, deduplicates, and persists domain lessons and preferences into agent MEMORY.md."""

    def __init__(self, base_storage_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_storage_dir or "/tmp/myrm_agents_memory")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        # agent_id -> dict[rule_id, CompoundedRule]
        self._rules: dict[str, dict[str, CompoundedRule]] = {}

    def _get_agent_dir(self, agent_id: str) -> Path:
        agent_dir = self._base_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir

    def _sync_to_markdown_file(self, agent_id: str) -> None:
        agent_dir = self._get_agent_dir(agent_id)
        memory_file = agent_dir / "MEMORY.md"

        agent_rules = list(self._rules.get(agent_id, {}).values())
        if not agent_rules:
            if memory_file.exists():
                memory_file.unlink()
            return

        lines: list[str] = [
            f"# Domain Compounding Memory: {agent_id}",
            f"> Last synced: {datetime.now(UTC).isoformat()}",
            "",
        ]

        # Group by rule type
        for r_type in RuleType:
            type_rules = [r for r in agent_rules if r.rule_type == r_type]
            if not type_rules:
                continue

            header_map = {
                RuleType.POSITIVE_PREFERENCE: "## 🌟 Positive Preferences (Favored Patterns)",
                RuleType.NEGATIVE_CONSTRAINT: "## ⛔ Negative Constraints (Prohibited Pitfalls)",
                RuleType.INSPECTION_LESSON: "## 🔍 Inspection & Troubleshooting Lessons",
            }
            lines.append(header_map[r_type])
            for r in type_rules:
                lines.append(
                    f"- **[{r.rule_id}]** {r.statement} "
                    f"*(Trigger: {r.trigger_condition} | Source: {r.evidence_source} | Hits: {r.hit_count})*"
                )
            lines.append("")

        memory_file.write_text("\n".join(lines), encoding="utf-8")

    def record_rule(
        self,
        agent_id: str,
        rule_type: RuleType,
        statement: str,
        trigger_condition: str,
        evidence_source: str,
    ) -> CompoundedRule:
        """Records a new compounded rule, deduplicating against existing rules for this agent."""
        cleaned_stmt = statement.strip()
        cleaned_trigger = trigger_condition.strip()

        if not cleaned_stmt:
            raise ValueError("Rule statement must not be empty.")

        with self._lock:
            agent_dict = self._rules.setdefault(agent_id, {})

            # Check duplicate statement
            for existing in agent_dict.values():
                if (
                    existing.statement.lower() == cleaned_stmt.lower()
                    and existing.rule_type == rule_type
                ):
                    existing.hit_count += 1
                    self._sync_to_markdown_file(agent_id)
                    return existing

            rule_id = f"rule_{uuid.uuid4().hex[:8]}"
            new_rule = CompoundedRule(
                rule_id=rule_id,
                agent_id=agent_id,
                rule_type=rule_type,
                statement=cleaned_stmt,
                trigger_condition=cleaned_trigger,
                evidence_source=evidence_source.strip(),
                hit_count=1,
                created_at=datetime.now(UTC),
            )
            agent_dict[rule_id] = new_rule
            self._sync_to_markdown_file(agent_id)
            return new_rule

    def list_rules(
        self,
        agent_id: str,
        rule_type: RuleType | None = None,
    ) -> list[CompoundedRule]:
        """Lists active compounded domain rules for an agent, optionally filtered by type."""
        with self._lock:
            agent_dict = self._rules.get(agent_id, {})
            rules = list(agent_dict.values())
            if rule_type is not None:
                rules = [r for r in rules if r.rule_type == rule_type]
            rules.sort(key=lambda r: r.hit_count, reverse=True)
            return rules

    def record_rule_hit(self, agent_id: str, rule_id: str) -> bool:
        """Increments usage hit count of a specific rule."""
        with self._lock:
            agent_dict = self._rules.get(agent_id, {})
            rule = agent_dict.get(rule_id)
            if rule is not None:
                rule.hit_count += 1
                self._sync_to_markdown_file(agent_id)
                return True
            return False

    def render_domain_memory_prompt(self, agent_id: str) -> str:
        """Renders accumulated rules into an actionable system prompt injection block."""
        rules = self.list_rules(agent_id)
        if not rules:
            return ""

        lines: list[str] = [
            f"## Accumulated Domain Lessons & Preferences ({len(rules)} rules active):"
        ]
        for r in rules:
            prefix = "⭐ [PREFERENCE]" if r.rule_type == RuleType.POSITIVE_PREFERENCE else (
                "⚠️ [CONSTRAINT]" if r.rule_type == RuleType.NEGATIVE_CONSTRAINT else "💡 [LESSON]"
            )
            lines.append(f"- {prefix} When: {r.trigger_condition} -> {r.statement}")
        return "\n".join(lines)
