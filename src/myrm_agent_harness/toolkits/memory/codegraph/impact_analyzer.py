"""Impact analysis engine evaluating modification blast radius and risk levels.

[INPUT]
- toolkits.memory.codegraph.store::CodeGraphMemoryStore (POS: CodeGraph memory store maintaining symbol
  topology and caller inversions.)
- toolkits.memory.codegraph.types::ImpactAnalysisReport, ImpactRiskLevel (POS: Domain models and type
  definitions for CodeGraph memory assets and impact analysis.)

[OUTPUT]
- CodeImpactAnalyzer: Evaluates the ripple effect and blast radius before modifying any symbol.

[POS]
Impact analysis engine evaluating modification blast radius and risk levels.
"""

from collections import deque

from myrm_agent_harness.toolkits.memory.codegraph.store import (
    CodeGraphMemoryStore,
)
from myrm_agent_harness.toolkits.memory.codegraph.types import (
    ImpactAnalysisReport,
    ImpactRiskLevel,
)


class CodeImpactAnalyzer:
    """Evaluates the ripple effect and blast radius before modifying any symbol."""

    def __init__(self, store: CodeGraphMemoryStore) -> None:
        self.store = store

    def analyze_symbol_impact(
        self,
        symbol_name: str,
        file_path: str = "",
        max_depth: int = 5,
    ) -> ImpactAnalysisReport:
        """Perform reverse BFS traversal to find all direct and indirect callers."""
        direct_callers = self.store.get_direct_callers(symbol_name)
        all_callers: set[str] = set()
        queue: deque[tuple[str, int]] = deque((c, 1) for c in direct_callers)

        visited_nodes: set[str] = set(direct_callers)
        caller_depths: dict[str, int] = {c: 1 for c in direct_callers}

        while queue:
            current_caller_id, depth = queue.popleft()
            all_callers.add(current_caller_id)

            if depth >= max_depth:
                continue

            # Extract caller's simple name to look up who calls this caller
            caller_sym = self.store.get_symbol(current_caller_id)
            caller_name = (
                caller_sym.name if caller_sym else current_caller_id.split("::")[-1]
            )

            upstream_callers = self.store.get_direct_callers(caller_name)
            for up in upstream_callers:
                if up not in visited_nodes:
                    visited_nodes.add(up)
                    caller_depths[up] = depth + 1
                    queue.append((up, depth + 1))

        indirect_callers = sorted(
            [c for c in all_callers if caller_depths.get(c, 1) > 1]
        )

        # Collect distinct affected files
        affected_files_set: set[str] = set()
        if file_path:
            affected_files_set.add(file_path)

        for caller_id in all_callers:
            if "::" in caller_id:
                affected_files_set.add(caller_id.split("::")[0])
            else:
                caller_sym = self.store.get_symbol(caller_id)
                if caller_sym:
                    affected_files_set.add(caller_sym.file_path)

        affected_files = sorted(affected_files_set)
        blast_radius = len(all_callers) + len(affected_files)

        risk_level = self._evaluate_risk_level(
            blast_radius=blast_radius,
            affected_files_count=len(affected_files),
        )

        recommendations = self._generate_safety_recommendations(
            symbol_name=symbol_name,
            risk_level=risk_level,
            direct_callers=direct_callers,
            affected_files=affected_files,
        )

        target_symbol_id = f"{file_path}::{symbol_name}" if file_path else symbol_name

        return ImpactAnalysisReport(
            target_symbol_id=target_symbol_id,
            target_symbol_name=symbol_name,
            file_path=file_path,
            blast_radius=blast_radius,
            risk_level=risk_level,
            direct_callers=direct_callers,
            indirect_callers=indirect_callers,
            affected_files=affected_files,
            safety_recommendations=recommendations,
        )

    def _evaluate_risk_level(
        self, blast_radius: int, affected_files_count: int
    ) -> ImpactRiskLevel:
        """Categorize risk level based on blast radius and file spread."""
        if blast_radius == 0:
            return ImpactRiskLevel.LOW
        if blast_radius <= 3 and affected_files_count <= 1:
            return ImpactRiskLevel.LOW
        if blast_radius <= 8 and affected_files_count <= 2:
            return ImpactRiskLevel.MEDIUM
        if blast_radius <= 20 and affected_files_count <= 4:
            return ImpactRiskLevel.HIGH
        return ImpactRiskLevel.CRITICAL

    def _generate_safety_recommendations(
        self,
        symbol_name: str,
        risk_level: ImpactRiskLevel,
        direct_callers: list[str],
        affected_files: list[str],
    ) -> list[str]:
        """Construct actionable precautions for developers or agents before edits."""
        recommendations: list[str] = []
        if risk_level in (ImpactRiskLevel.HIGH, ImpactRiskLevel.CRITICAL):
            recommendations.append(
                f"Modifying '{symbol_name}' impacts {len(affected_files)} files. "
                "Ensure backward compatibility or execute systematic refactoring."
            )
            recommendations.append(
                "Run test suites covering caller modules: "
                f"{', '.join(affected_files[:3])}."
            )
        elif risk_level == ImpactRiskLevel.MEDIUM:
            recommendations.append(
                f"Verify {len(direct_callers)} direct callers before changing signature."
            )
        else:
            recommendations.append(
                f"Safe to proceed: localized change with low ripple effect on '{symbol_name}'."
            )
        return recommendations
