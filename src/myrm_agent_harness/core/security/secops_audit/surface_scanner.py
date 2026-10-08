"""Automated High-Risk Surface Path and Diff Scanner.

[INPUT]
- List of modified file paths or diff inventory.

[OUTPUT]
- DiffSurfaceAnalysisResult with identified risk categories, applied GitHub labels,
  and mandatory multi-party review gate assertions.

[POS]
- Harness core security module inspired by Mike Julian engineering SecOps governance.
- Identifies critical attack surfaces (API, Auth, MCP, Migrations, Skills) before merge.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence

from myrm_agent_harness.core.security.secops_audit.types import (
    DiffSurfaceAnalysisResult,
    RiskCategory,
    SurfaceLabel,
    SurfaceMatch,
)

# Rule definitions: (glob_patterns, category, label, reason)
_SURFACE_RULES: tuple[tuple[tuple[str, ...], RiskCategory, SurfaceLabel, str], ...] = (
    (
        ("*/security/*", "*/auth/*", "*auth*.py", "*security*.py", "*enclave*.py"),
        RiskCategory.AUTH_SECURITY,
        SurfaceLabel.SEC_AUTH_CHANGE,
        "Modification touches core authentication, authorization, or security enclave boundary.",
    ),
    (
        ("*/skills/*.md", "*/skills/*/*.md", "*SKILL.md", "skills/*"),
        RiskCategory.SKILL_MUTATION,
        SurfaceLabel.AGENT_SKILL_MUTATION,
        "Modification alters Agent Skill definition, prompting instructions, or execution tools.",
    ),
    (
        ("*/mcp/*", "*/mcp.json", "*.mcp/*.json", "*mcp_config*"),
        RiskCategory.MCP_CONFIG,
        SurfaceLabel.MCP_CONFIG_MUTATION,
        "Modification exposes or alters Model Context Protocol (MCP) tool registrations.",
    ),
    (
        ("*/alembic/*", "*/migrations/*", "*alembic/versions/*"),
        RiskCategory.DATABASE_MIGRATION,
        SurfaceLabel.DB_MIGRATION_SURFACE,
        "Modification touches database schema migrations or persistence structures.",
    ),
    (
        ("*/api/*", "*router*.py", "*endpoints*.py", "app/api/*"),
        RiskCategory.PUBLIC_API,
        SurfaceLabel.RISK_HIGH_SURFACE,
        "Modification touches public or internal REST/WebSocket API endpoints.",
    ),
)


class HighRiskSurfaceScanner:
    """Scanner that classifies path diffs and enforces SecOps review gates."""

    @staticmethod
    def classify_path(path: str) -> list[SurfaceMatch]:
        """Classify a single file path against all high-risk surface rules."""
        normalized = path.replace("\\", "/").strip("/")
        matches: list[SurfaceMatch] = []

        for patterns, category, label, reason in _SURFACE_RULES:
            for pattern in patterns:
                # Test against full normalized path and its filename
                if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized, f"*/{pattern}"):
                    matches.append(
                        SurfaceMatch(
                            path=normalized,
                            category=category,
                            suggested_label=label,
                            reason=reason,
                        )
                    )
                    break

        return matches

    def scan_paths(self, paths: Sequence[str]) -> DiffSurfaceAnalysisResult:
        """Scan a sequence of file paths and return a consolidated SecOps gate result."""
        all_matches: list[SurfaceMatch] = []
        labels_set: set[str] = set()

        for p in paths:
            if not p or not p.strip():
                continue
            matched = self.classify_path(p)
            for m in matched:
                all_matches.append(m)
                labels_set.add(m.suggested_label.value)

        has_high_risk = len(all_matches) > 0
        sorted_labels = tuple(sorted(labels_set))

        return DiffSurfaceAnalysisResult(
            total_files_scanned=len(paths),
            high_risk_detected=has_high_risk,
            requires_multi_party_review=has_high_risk,
            applied_labels=sorted_labels,
            matches=tuple(all_matches),
        )
