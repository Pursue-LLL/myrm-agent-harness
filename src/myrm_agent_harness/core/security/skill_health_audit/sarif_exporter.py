"""
[POS] src/myrm_agent_harness/core/security/skill_health_audit/sarif_exporter.py
[INPUT] typing, types
[OUTPUT] Sarif210Exporter
SARIF 2.1.0 (Static Analysis Results Interchange Format) formatter for skill scan findings.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json

from .types import TaintFlowFinding, TaintSeverity


class Sarif210Exporter:
    """Format AST taint and skill audit findings into OASIS SARIF 2.1.0 standard schema."""

    SARIF_SCHEMA_URI: str = (
        "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    )

    @staticmethod
    def _map_severity_to_sarif_level(severity: TaintSeverity) -> str:
        """Map internal TaintSeverity to standard SARIF 2.1.0 level."""
        if severity == TaintSeverity.CRITICAL_BLOCK:
            return "error"
        if severity == TaintSeverity.HIGH:
            return "error"
        if severity == TaintSeverity.WARNING:
            return "warning"
        return "note"

    def export_sarif(
        self,
        skill_name: str,
        findings: tuple[TaintFlowFinding, ...],
    ) -> dict[str, str | int | list[dict[str, str | int]]]:
        """Produce standard SARIF 2.1.0 dictionary representation."""
        results_list: list[dict[str, str | int]] = []
        rules_list: list[dict[str, str | int]] = [
            {
                "id": "MYRM-SKILL-001",
                "name": "UndeclaredNetworkExfiltration",
                "shortDescription": "Potential covert data exfiltration into undeclared network sink",
            },
            {
                "id": "MYRM-SKILL-002",
                "name": "DangerousSystemExecution",
                "shortDescription": "Execution of unconstrained OS-level system command",
            },
        ]

        for finding in findings:
            rule_id = (
                "MYRM-SKILL-002" if finding.source_type == "syscall" else "MYRM-SKILL-001"
            )
            level = self._map_severity_to_sarif_level(finding.severity)
            result_item: dict[str, str | int] = {
                "ruleId": rule_id,
                "level": level,
                "message": finding.description,
                "line": finding.line_number,
                "symbol": finding.symbol,
            }
            results_list.append(result_item)

        runs_list: list[dict[str, str | int]] = [
            {
                "tool_name": "Myrm-Skill-Health-Auditor",
                "tool_version": "1.0.0",
                "target_skill": skill_name,
                "findings_count": len(results_list),
            }
        ]

        return {
            "version": "2.1.0",
            "$schema": self.SARIF_SCHEMA_URI,
            "runs": runs_list,
            "rules": rules_list,
            "results": results_list,
        }

    def export_sarif_json(
        self,
        skill_name: str,
        findings: tuple[TaintFlowFinding, ...],
    ) -> str:
        """Serialize findings into formatted SARIF 2.1.0 JSON string."""
        data = self.export_sarif(skill_name, findings)
        return json.dumps(data, indent=2)
