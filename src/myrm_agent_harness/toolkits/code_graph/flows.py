"""Execution flow detection and analysis.

Identifies entry points (main functions, CLI handlers, API endpoints, test
runners) and traces forward execution flows through the call graph.

[INPUT]
- CodeGraphStore (POS: opened graph store with populated data)

[OUTPUT]
- FlowAnalyzer: execution flow detection and tracing
- EntryPoint: detected entry point with metadata
- FlowTrace: forward execution trace from an entry point

[POS]
Execution flow layer that identifies how code is invoked and traces call
chains. Helps Agent understand the runtime execution path for debugging
and impact analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore

logger = logging.getLogger(__name__)

_ENTRY_POINT_PATTERNS: dict[str, list[str]] = {
    "python": [
        "main", "__main__", "cli", "app", "run",
        "handle", "handler", "endpoint", "view",
    ],
    "javascript": [
        "main", "index", "app", "server",
        "handler", "middleware",
    ],
    "go": [
        "main", "Main", "Run",
        "Handler", "ServeHTTP",
    ],
    "java": [
        "main", "run", "handle",
        "doGet", "doPost", "service",
    ],
    "rust": [
        "main", "run", "handle",
    ],
}

MAX_TRACE_DEPTH = 10
MAX_TRACE_NODES = 100


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """A detected code entry point."""

    qualified_name: str
    file_path: str
    kind: str
    name: str
    entry_type: str  # "main", "cli", "api", "test", "init"
    line: int = 0


@dataclass(slots=True)
class FlowStep:
    """A single step in an execution flow trace."""

    qualified_name: str
    file_path: str
    kind: str
    name: str
    depth: int
    edge_type: str = "CALLS"


@dataclass(slots=True)
class FlowTrace:
    """Forward execution trace from an entry point."""

    entry_point: str
    steps: list[FlowStep] = field(default_factory=list)
    depth_reached: int = 0
    files_touched: list[str] = field(default_factory=list)


class FlowAnalyzer:
    """Detects entry points and traces execution flows."""

    def __init__(self, store: CodeGraphStore) -> None:
        self._store = store

    def detect_entry_points(self, *, max_results: int = 50) -> list[EntryPoint]:
        """Find entry points: functions with no callers or matching known patterns."""
        db = self._store.connection
        entry_points: list[EntryPoint] = []

        called_targets: set[str] = set()
        for row in db.execute(
            "SELECT DISTINCT target_qualified FROM edges WHERE kind = 'CALLS'"
        ).fetchall():
            called_targets.add(row["target_qualified"])

        rows = db.execute(
            """SELECT qualified_name, file_path, kind, name, language, line_start, is_test
               FROM nodes
               WHERE kind IN ('Function', 'Method')
               ORDER BY line_start"""
        ).fetchall()

        for row in rows:
            qn = row["qualified_name"]
            name = row["name"]
            language = row["language"] if row["language"] else "python"
            is_test = bool(row["is_test"])

            entry_type = self._classify_entry(name, language, is_test, qn, called_targets)
            if entry_type:
                entry_points.append(EntryPoint(
                    qualified_name=qn,
                    file_path=row["file_path"],
                    kind=row["kind"],
                    name=name,
                    entry_type=entry_type,
                    line=row["line_start"],
                ))

                if len(entry_points) >= max_results:
                    break

        return entry_points

    def trace_flow(
        self,
        entry_qualified_name: str,
        *,
        max_depth: int = MAX_TRACE_DEPTH,
        max_nodes: int = MAX_TRACE_NODES,
    ) -> FlowTrace:
        """Trace forward execution flow from an entry point via BFS."""
        db = self._store.connection
        trace = FlowTrace(entry_point=entry_qualified_name)
        visited: set[str] = {entry_qualified_name}
        queue: list[tuple[str, int]] = [(entry_qualified_name, 0)]
        files_touched: set[str] = set()

        while queue and len(trace.steps) < max_nodes:
            current, depth = queue.pop(0)
            if depth > max_depth:
                continue
            trace.depth_reached = max(trace.depth_reached, depth)

            rows = db.execute(
                """SELECT e.target_qualified, e.kind AS edge_kind,
                          n.file_path, n.kind, n.name
                   FROM edges e
                   JOIN nodes n ON n.qualified_name = e.target_qualified
                   WHERE e.source_qualified = ?
                     AND e.kind IN ('CALLS', 'REFERENCES')
                   ORDER BY e.confidence DESC""",
                (current,),
            ).fetchall()

            for row in rows:
                tq = row["target_qualified"]
                if tq in visited:
                    continue
                visited.add(tq)

                trace.steps.append(FlowStep(
                    qualified_name=tq,
                    file_path=row["file_path"],
                    kind=row["kind"],
                    name=row["name"],
                    depth=depth + 1,
                    edge_type=row["edge_kind"],
                ))
                files_touched.add(row["file_path"])

                if depth + 1 < max_depth and len(trace.steps) < max_nodes:
                    queue.append((tq, depth + 1))

        trace.files_touched = sorted(files_touched)
        return trace

    @staticmethod
    def _classify_entry(
        name: str,
        language: str,
        is_test: bool,
        qualified_name: str,
        called_targets: set[str],
    ) -> str:
        if is_test:
            return "test"

        patterns = _ENTRY_POINT_PATTERNS.get(language, [])
        name_lower = name.lower()

        if name_lower in ("main", "__main__"):
            return "main"

        if any(p in name_lower for p in ("cli", "command", "cmd")):
            return "cli"

        if any(p in name_lower for p in ("handle", "handler", "endpoint", "view", "route")):
            return "api"

        if any(p in name_lower for p in ("setup", "init", "configure", "bootstrap")):
            return "init"

        if name_lower in patterns:
            return "main"

        if qualified_name not in called_targets and name_lower not in (
            "__init__", "__new__", "__del__", "__repr__", "__str__",
        ):
            return ""

        return ""
