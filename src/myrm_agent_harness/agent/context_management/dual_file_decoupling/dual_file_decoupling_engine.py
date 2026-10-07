"""Dual-File Decoupled Architecture Engine for AGENTS.md and 00_项目总览.md (Item 217).

[INPUT]
- Static rule text (AGENTS.md) and dynamic operational overview text (00_项目总览.md).
- DualFileDecouplingConfig: Configuration governing file names and schemas.

[OUTPUT]
- DualFileContextEnvelope: Decoupled invariant and active status frames for prompt assembly.
- Strongly typed 5-section parser, renderer, and incremental status reflector.

[POS]
- Eliminates context confusion and prompt dilution by physically separating permanent rules
- from fast-moving project progress into an invariant channel and an active status channel.
"""

from __future__ import annotations

import hashlib
import re
import time

from .dual_file_decoupling_types import (
    DualFileContextEnvelope,
    DualFileDecouplingConfig,
    DynamicOverviewSections,
    ProjectRuleInvariantSpec,
)


class DualFileProjectContextDecouplingEngine:
    """Engine parsing, rendering, and assembling decoupled static rules and dynamic status."""

    def __init__(self, config: DualFileDecouplingConfig | None = None) -> None:
        self._config = config or DualFileDecouplingConfig()

    @property
    def config(self) -> DualFileDecouplingConfig:
        """Returns engine configuration."""
        return self._config

    def parse_static_rules(
        self,
        raw_text: str,
        source_path: str = "AGENTS.md",
    ) -> ProjectRuleInvariantSpec:
        """Parses static rules file, extracting invariant principles and boundaries."""
        sha256_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        principles: list[str] = []
        forbidden: list[str] = []

        for line in lines:
            line_lower = line.lower()
            cleaned = line.lstrip("-*# ").strip()
            if any(k in line_lower for k in ("必须", "always", "rule", "原则", "红线")):
                principles.append(cleaned)
            if any(k in line_lower for k in ("禁止", "forbidden", "never", "严禁", "do not")):
                forbidden.append(cleaned)

        return ProjectRuleInvariantSpec(
            rule_source_path=source_path,
            raw_content=raw_text,
            core_principles=principles,
            forbidden_actions=forbidden,
            sha256_hash=sha256_hash,
        )

    def parse_dynamic_overview(self, raw_text: str) -> DynamicOverviewSections:
        """Parses standard 5-section markdown into strongly typed DynamicOverviewSections."""
        current_goal = ""
        facts: list[str] = []
        deliverables: list[str] = []
        blockers: list[str] = []
        next_actions: list[str] = []

        sections_regex = re.compile(
            r"【(当前阶段目标|已拍板事实与确认标准|现有成果清单|当前卡点与待决策事项|下一步具体交付动作)】",
            re.MULTILINE,
        )
        splits = sections_regex.split(raw_text)

        if len(splits) > 1:
            # splits: [preamble, section_name_1, section_body_1, section_name_2, section_body_2, ...]
            for i in range(1, len(splits), 2):
                sec_name = splits[i].strip()
                sec_body = splits[i + 1].strip() if i + 1 < len(splits) else ""
                items = [
                    item.lstrip("-*1234567890. ").strip()
                    for item in sec_body.splitlines()
                    if item.strip() and not item.strip().startswith("#")
                ]

                if sec_name == "当前阶段目标":
                    current_goal = sec_body.splitlines()[0].strip() if sec_body else ""
                elif sec_name == "已拍板事实与确认标准":
                    facts.extend(items)
                elif sec_name == "现有成果清单":
                    deliverables.extend(items)
                elif sec_name == "当前卡点与待决策事项":
                    blockers.extend(items)
                elif sec_name == "下一步具体交付动作":
                    next_actions.extend(items)
        else:
            # Fallback if no exact 5-section bracket tags found
            current_goal = raw_text.strip().splitlines()[0] if raw_text.strip() else ""

        return DynamicOverviewSections(
            current_phase_goal=current_goal,
            established_facts=facts,
            deliverables=deliverables,
            blockers_and_decisions=blockers,
            next_actions=next_actions,
            last_updated_at=time.time(),
        )

    def render_dynamic_overview_markdown(self, sections: DynamicOverviewSections) -> str:
        """Renders standard 5-section Markdown dashboard string."""
        lines: list[str] = [
            f"# {self._config.dynamic_status_filename}（流动工作看板）",
            "",
            "## 【当前阶段目标】",
            sections.current_phase_goal or "暂无明确目标",
            "",
            "## 【已拍板事实与确认标准】",
        ]
        if sections.established_facts:
            lines.extend(f"- {fact}" for fact in sections.established_facts)
        else:
            lines.append("- （暂无）")

        lines.extend(["", "## 【现有成果清单】"])
        if sections.deliverables:
            lines.extend(f"- {d}" for d in sections.deliverables)
        else:
            lines.append("- （暂无）")

        lines.extend(["", "## 【当前卡点与待决策事项】"])
        if sections.blockers_and_decisions:
            lines.extend(f"- {b}" for b in sections.blockers_and_decisions)
        else:
            lines.append("- 无阻碍，进行中")

        lines.extend(["", "## 【下一步具体交付动作】"])
        if sections.next_actions:
            lines.extend(f"- {a}" for a in sections.next_actions)
        else:
            lines.append("- （等待用户指示）")

        return "\n".join(lines)

    def reflect_status_update(
        self,
        current_sections: DynamicOverviewSections,
        new_goal: str | None = None,
        added_facts: list[str] | None = None,
        added_deliverables: list[str] | None = None,
        updated_blockers: list[str] | None = None,
        next_actions: list[str] | None = None,
    ) -> DynamicOverviewSections:
        """Incrementally updates active operational sections when milestones are achieved."""
        goal = new_goal if new_goal is not None else current_sections.current_phase_goal
        facts = list(current_sections.established_facts)
        if added_facts:
            facts.extend(f for f in added_facts if f not in facts)

        deliverables = list(current_sections.deliverables)
        if added_deliverables:
            deliverables.extend(d for d in added_deliverables if d not in deliverables)

        blockers = (
            list(updated_blockers)
            if updated_blockers is not None
            else list(current_sections.blockers_and_decisions)
        )
        actions = (
            list(next_actions)
            if next_actions is not None
            else list(current_sections.next_actions)
        )

        return DynamicOverviewSections(
            current_phase_goal=goal,
            established_facts=facts,
            deliverables=deliverables,
            blockers_and_decisions=blockers,
            next_actions=actions,
            last_updated_at=time.time(),
        )

    def build_dual_file_envelope(
        self,
        static_rules_text: str,
        dynamic_overview_text: str,
    ) -> DualFileContextEnvelope:
        """Assembles decoupled static invariant and active status frames for prompt assembly."""
        rule_hash = hashlib.sha256(static_rules_text.encode("utf-8")).hexdigest()
        status_hash = hashlib.sha256(dynamic_overview_text.encode("utf-8")).hexdigest()

        # Channel 1: Static Invariant System Frame (Cache-Aligned)
        system_invariant_frame = (
            f"[PROJECT STATIC INVARIANT RULES: {self._config.static_rule_filename}]\n"
            f"Digest: {rule_hash}\n"
            f"{static_rules_text.strip()}\n"
            f"[END INVARIANT RULES]"
        )

        # Channel 2: Dynamic Live Status Frame (Active Note)
        dynamic_status_frame = (
            f"[PROJECT ACTIVE STATUS DASHBOARD: {self._config.dynamic_status_filename}]\n"
            f"Digest: {status_hash}\n"
            f"{dynamic_overview_text.strip()}\n"
            f"[END ACTIVE STATUS DASHBOARD]"
        )

        # Estimated tokens (~4 chars per token)
        inv_tokens = max(1, len(system_invariant_frame) // 4)
        stat_tokens = max(1, len(dynamic_status_frame) // 4)

        return DualFileContextEnvelope(
            system_invariant_frame=system_invariant_frame,
            dynamic_status_frame=dynamic_status_frame,
            rule_hash=rule_hash,
            status_hash=status_hash,
            cached_invariant_tokens_estimate=inv_tokens,
            active_status_tokens_estimate=stat_tokens,
        )
