"""Heuristic project root sniffer and directory traversal anchor.

[INPUT]
- workspace_types: DiscoveredRootResult, MultiSessionWorkspaceConfig, RootIndicatorKind.

[OUTPUT]
- ProjectRootSniffer: Traverses upward from any starting path within safety boundaries,
  evaluating VCS, monorepo, and package markers to discover authentic repository roots.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.multi_session_workspace
- Module: project_root_sniffer.py
"""

from pathlib import Path
from typing import List, Optional

from myrm_agent_harness.agent.context_management.multi_session_workspace.workspace_types import (
    DiscoveredRootResult,
    MultiSessionWorkspaceConfig,
    RootIndicatorKind,
)


class ProjectRootSniffer:
    """Discovers authentic project roots to eliminate manual path navigation friction."""

    def __init__(self, config: Optional[MultiSessionWorkspaceConfig] = None) -> None:
        self._config = config or MultiSessionWorkspaceConfig()

    def discover_root(
        self,
        starting_path: Path,
        sandbox_boundary: Optional[Path] = None,
    ) -> DiscoveredRootResult:
        """Traverses upward to identify the primary project root based on heuristics.

        Args:
            starting_path: Path to start searching from (file or directory).
            sandbox_boundary: Optional boundary past which upward traversal is forbidden.

        Returns:
            DiscoveredRootResult containing root location, confidence score, and indicators.
        """
        # Resolve path safely
        try:
            curr = starting_path.resolve()
        except Exception:
            curr = starting_path.absolute()

        if curr.is_file():
            curr = curr.parent

        resolved_boundary: Optional[Path] = None
        if sandbox_boundary is not None:
            try:
                resolved_boundary = sandbox_boundary.resolve()
            except Exception:
                resolved_boundary = sandbox_boundary.absolute()

        candidates: List[tuple[Path, float, List[str], bool, int]] = []
        depth = 0
        search_ptr = curr

        while depth <= self._config.max_upward_traversal_depth:
            # Check sandbox boundary: stop if we breached outside boundary
            if resolved_boundary is not None:
                try:
                    search_ptr.relative_to(resolved_boundary)
                except ValueError:
                    # search_ptr is outside sandbox boundary; stop ascending
                    break

            found_indicators: List[str] = []
            score = 0.0
            is_monorepo = False

            # Check standard indicators
            for marker, kind in self._config.standard_root_indicators.items():
                marker_path = search_ptr / marker
                if marker_path.exists():
                    found_indicators.append(marker)
                    if kind == RootIndicatorKind.VCS:
                        score += 50.0
                    elif kind == RootIndicatorKind.BUILD_CONFIG:
                        score += 30.0

            # Check monorepo indicators
            for mono_marker in self._config.monorepo_indicators:
                if (search_ptr / mono_marker).exists():
                    found_indicators.append(mono_marker)
                    is_monorepo = True
                    score += 40.0

            if found_indicators:
                # Cap score at 100.0
                normalized_score = min(score, 100.0)
                candidates.append((search_ptr, normalized_score, found_indicators, is_monorepo, depth))

            # Stop when hitting system root
            if search_ptr.parent == search_ptr:
                break

            # If current directory is exactly sandbox boundary, do not ascend further
            if resolved_boundary is not None and search_ptr == resolved_boundary:
                break

            search_ptr = search_ptr.parent
            depth += 1

        if not candidates:
            # Fallback to starting directory
            return DiscoveredRootResult(
                starting_path=curr,
                discovered_root=curr,
                confidence_score=0.0,
                indicators_found=tuple(),
                is_monorepo_root=False,
                traversal_depth=0,
                diagnostic_reason="No project indicators detected; defaulted to starting directory.",
            )

        # Select candidate with highest confidence score, preferring monorepo/VCS roots
        best_candidate = max(candidates, key=lambda c: c[1])
        root_path, conf_score, indicators, is_mono, d = best_candidate

        reason = (
            f"Identified project root at '{root_path}' with confidence {conf_score:.1f}% "
            f"via indicators: {', '.join(indicators)}."
        )

        return DiscoveredRootResult(
            starting_path=curr,
            discovered_root=root_path,
            confidence_score=conf_score,
            indicators_found=tuple(indicators),
            is_monorepo_root=is_mono,
            traversal_depth=d,
            diagnostic_reason=reason,
        )
