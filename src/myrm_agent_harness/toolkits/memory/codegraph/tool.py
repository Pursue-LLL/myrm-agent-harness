"""Agent-facing meta tool for evaluating code modification impact.

[INPUT]
- toolkits.memory.codegraph.impact_analyzer::CodeImpactAnalyzer (POS: Impact analysis engine evaluating
  modification blast radius and risk levels.)
- toolkits.memory.codegraph.store::CodeGraphMemoryStore (POS: CodeGraph memory store maintaining symbol
  topology and caller inversions.)

[OUTPUT]
- CodeImpactAnalysisTool: Tool exposed to agents to inspect caller blast radius before code edits.

[POS]
Agent-facing meta tool for evaluating code modification impact.
"""

from myrm_agent_harness.toolkits.memory.codegraph.impact_analyzer import (
    CodeImpactAnalyzer,
)
from myrm_agent_harness.toolkits.memory.codegraph.store import (
    CodeGraphMemoryStore,
)


class CodeImpactAnalysisTool:
    """Tool exposed to agents to inspect caller blast radius before code edits."""

    def __init__(self, store: CodeGraphMemoryStore) -> None:
        self.store = store
        self.analyzer = CodeImpactAnalyzer(store=store)

    def analyze_impact(
        self, symbol_name: str, file_path: str = ""
    ) -> dict[str, str | int | list[str]]:
        """Evaluate ripple effect and risk level when modifying a given code symbol."""
        report = self.analyzer.analyze_symbol_impact(
            symbol_name=symbol_name,
            file_path=file_path,
        )

        return {
            "target_symbol_id": report.target_symbol_id,
            "target_symbol_name": report.target_symbol_name,
            "file_path": report.file_path,
            "blast_radius": report.blast_radius,
            "risk_level": report.risk_level.value,
            "direct_callers": report.direct_callers,
            "indirect_callers": report.indirect_callers,
            "affected_files": report.affected_files,
            "safety_recommendations": report.safety_recommendations,
        }
