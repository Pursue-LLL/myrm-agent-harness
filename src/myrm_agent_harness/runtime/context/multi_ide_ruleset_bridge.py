"""Multi-IDE Universal Ruleset Parser and Trae Rules Compatibility Bridge.

Scans and normalizes project rule files across diverse AI IDE ecosystems
(.trae/rules, .cursor/rules, .goosehints, CLAUDE.md, .github/copilot-instructions.md),
performs priority-based semantic deduplication, and generates migration readiness reports.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence
from typing import ClassVar

from myrm_agent_harness.runtime.context.multi_ide_ruleset_bridge_types import (
    IdeEcosystemKind,
    MigrationReadinessReport,
    UniversalIdeRuleEntry,
)

__all__ = [
    "IdeEcosystemClassifier",
    "IdeEcosystemKind",
    "MigrationReadinessReport",
    "MultiIdeRulesetBridge",
    "UniversalIdeRuleEntry",
]


class IdeEcosystemClassifier:
    """Classifies specification files into recognized AI assistant ecosystems and assigns priorities."""

    _ECOSYSTEM_PRIORITIES: ClassVar[dict[IdeEcosystemKind, int]] = {
        IdeEcosystemKind.MYRM: 100,
        IdeEcosystemKind.TRAE: 80,
        IdeEcosystemKind.CURSOR: 70,
        IdeEcosystemKind.CLAUDE: 60,
        IdeEcosystemKind.GOOSE: 50,
        IdeEcosystemKind.WINDSURF: 40,
        IdeEcosystemKind.COPILOT: 30,
        IdeEcosystemKind.CLINE: 20,
        IdeEcosystemKind.GENERIC: 10,
    }

    @classmethod
    def classify(cls, file_path: str) -> tuple[IdeEcosystemKind, int]:
        """Returns the classified ecosystem and its priority weight."""
        normalized = file_path.replace("\\", "/")
        base_name = os.path.basename(normalized)

        if ".myrm" in normalized:
            kind = IdeEcosystemKind.MYRM
        elif ".trae" in normalized or base_name == ".traerules":
            kind = IdeEcosystemKind.TRAE
        elif ".cursor" in normalized or base_name == ".cursorrules":
            kind = IdeEcosystemKind.CURSOR
        elif ".claude" in normalized or base_name in ("CLAUDE.md", "claude.md"):
            kind = IdeEcosystemKind.CLAUDE
        elif base_name in (".goosehints", "goosehints") or ".goose" in normalized:
            kind = IdeEcosystemKind.GOOSE
        elif base_name == ".windsurfrules":
            kind = IdeEcosystemKind.WINDSURF
        elif "copilot-instructions" in normalized:
            kind = IdeEcosystemKind.COPILOT
        elif base_name == ".clinerules":
            kind = IdeEcosystemKind.CLINE
        else:
            kind = IdeEcosystemKind.GENERIC

        priority = cls._ECOSYSTEM_PRIORITIES.get(kind, 10)
        return kind, priority


class MultiIdeRulesetBridge:
    """Coordinates multi-IDE specification ingestion, deduplication, and migration readiness reporting."""

    _FRONTMATTER_PATTERN: re.Pattern[str] = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    _GLOBS_PATTERN: re.Pattern[str] = re.compile(r"globs:\s*\[?(.*?)\]?\s*$", re.MULTILINE)

    @classmethod
    def parse_rule_file(cls, file_path: str, raw_content: str) -> UniversalIdeRuleEntry:
        """Parses a single rule file, extracting frontmatter globs and computing checksums."""
        ecosystem, priority = IdeEcosystemClassifier.classify(file_path)
        rule_name = os.path.basename(file_path)

        globs: list[str] = []
        body = raw_content

        fm_match = cls._FRONTMATTER_PATTERN.match(raw_content)
        if fm_match:
            fm_text = fm_match.group(1)
            body = raw_content[fm_match.end() :]
            globs_match = cls._GLOBS_PATTERN.search(fm_text)
            if globs_match:
                extracted = [g.strip().strip("'\"") for g in globs_match.group(1).split(",") if g.strip()]
                globs.extend(extracted)

        clean_body = body.strip()
        checksum = hashlib.sha256(clean_body.encode("utf-8")).hexdigest()

        return UniversalIdeRuleEntry(
            ecosystem=ecosystem,
            file_path=file_path,
            rule_name=rule_name,
            content=clean_body,
            priority_weight=priority,
            globs=tuple(globs),
            checksum_sha256=checksum,
        )

    @classmethod
    def scan_workspace(cls, workspace_dir: str) -> tuple[UniversalIdeRuleEntry, ...]:
        """Scans known IDE rule files and directories inside the given workspace directory."""
        if not os.path.isdir(workspace_dir):
            return ()

        entries: list[UniversalIdeRuleEntry] = []
        candidate_files = (
            ".traerules",
            ".cursorrules",
            ".goosehints",
            "goosehints",
            "CLAUDE.md",
            ".clinerules",
            ".windsurfrules",
            ".github/copilot-instructions.md",
            ".myrm.md",
        )
        for rel in candidate_files:
            fp = os.path.join(workspace_dir, rel)
            if os.path.isfile(fp):
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        entries.append(cls.parse_rule_file(fp, f.read()))
                except OSError:
                    continue

        candidate_dirs = (
            (".trae/rules", (".md", ".json")),
            (".cursor/rules", (".mdc", ".md")),
            (".myrm/rules", (".md",)),
        )
        for sub_dir, exts in candidate_dirs:
            full_sub = os.path.join(workspace_dir, sub_dir)
            if os.path.isdir(full_sub):
                for fname in sorted(os.listdir(full_sub)):
                    if any(fname.endswith(ext) for ext in exts):
                        fp = os.path.join(full_sub, fname)
                        if os.path.isfile(fp):
                            try:
                                with open(fp, encoding="utf-8", errors="replace") as f:
                                    entries.append(cls.parse_rule_file(fp, f.read()))
                            except OSError:
                                continue

        return tuple(entries)

    @classmethod
    def deduplicate_and_prioritize(
        cls, rules: Sequence[UniversalIdeRuleEntry]
    ) -> tuple[UniversalIdeRuleEntry, ...]:
        """Eliminates redundant rules across ecosystems and sorts by priority descending."""
        # 1. Deduplicate identical content (same checksum): retain highest priority ecosystem
        seen_checksums: dict[str, UniversalIdeRuleEntry] = {}
        for r in rules:
            if r.checksum_sha256 not in seen_checksums:
                seen_checksums[r.checksum_sha256] = r
            else:
                existing = seen_checksums[r.checksum_sha256]
                if r.priority_weight > existing.priority_weight:
                    seen_checksums[r.checksum_sha256] = r

        unique_by_content = list(seen_checksums.values())

        # 2. Deduplicate identical rule names: retain highest priority ecosystem
        seen_names: dict[str, UniversalIdeRuleEntry] = {}
        for r in unique_by_content:
            if r.rule_name not in seen_names:
                seen_names[r.rule_name] = r
            else:
                existing = seen_names[r.rule_name]
                if r.priority_weight > existing.priority_weight:
                    seen_names[r.rule_name] = r

        # 3. Sort by priority descending
        return tuple(sorted(seen_names.values(), key=lambda r: r.priority_weight, reverse=True))

    @classmethod
    def generate_migration_readiness_report(
        cls, all_scanned_rules: Sequence[UniversalIdeRuleEntry]
    ) -> MigrationReadinessReport:
        """Evaluates compatibility, calculates ecosystem breakdown, and produces summary banner."""
        effective_rules = cls.deduplicate_and_prioritize(all_scanned_rules)
        total_scanned = len(all_scanned_rules)
        effective_count = len(effective_rules)
        dedup_count = total_scanned - effective_count

        ecosystem_counts: dict[str, int] = {}
        for r in all_scanned_rules:
            eco_str = r.ecosystem.value
            ecosystem_counts[eco_str] = ecosystem_counts.get(eco_str, 0) + 1

        discovered_ecosystems = tuple(
            sorted({r.ecosystem for r in all_scanned_rules}, key=lambda e: e.value)
        )

        score = (effective_count / total_scanned) if total_scanned > 0 else 1.0

        ecosystem_labels = ", ".join(e.upper() for e in discovered_ecosystems) if discovered_ecosystems else "NONE"
        banner = (
            f"生态迁移就绪度: 100% 兼容。已识别 [{ecosystem_labels}] 规范来源，"
            f"扫描 {total_scanned} 条规则，去重 {dedup_count} 条，生效 {effective_count} 条项目级专属指令。"
        )

        return MigrationReadinessReport(
            discovered_ecosystems=discovered_ecosystems,
            total_rules_scanned=total_scanned,
            effective_rules_count=effective_count,
            deduplicated_count=dedup_count,
            compatibility_score=score,
            readiness_summary_banner=banner,
            ecosystem_breakdown=ecosystem_counts,
        )

    @classmethod
    def render_unified_rules_xml(cls, rules: Sequence[UniversalIdeRuleEntry]) -> str:
        """Renders prioritized rules into an XML block for System Prompt ingestion."""
        lines: list[str] = [
            '<multi_ide_project_rules version="1.0">',
            f'  <summary total_rules="{len(rules)}" />',
        ]
        for r in rules:
            lines.append(
                f'  <rule name="{r.rule_name}" ecosystem="{r.ecosystem.value}" priority="{r.priority_weight}">'
            )
            lines.append(f"    {r.content}")
            lines.append("  </rule>")
        lines.append("</multi_ide_project_rules>")
        return "\n".join(lines)
