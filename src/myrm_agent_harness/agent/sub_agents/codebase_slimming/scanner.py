"""Dead code and redundant topology scanner for Python codebases.

[INPUT]
- .types::DeadCodeCandidate, DeadCodeScanReport, SlimmingRiskLevel (POS: Slimming data models)

[OUTPUT]
- DeadCodeTopologyScanner: AST and reference-based dead code and redundant export analyzer.

[POS]
Static analysis and topology parsing to identify pruning targets without runtime overhead.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from myrm_agent_harness.agent.sub_agents.codebase_slimming.types import (
    DeadCodeCandidate,
    DeadCodeScanReport,
    SlimmingRiskLevel,
)

_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
    }
)


class DeadCodeTopologyScanner:
    """Performs static analysis across a workspace to detect dead symbols and unused functions."""

    @classmethod
    def scan_workspace(cls, root_dir: Path | str) -> DeadCodeScanReport:
        root = Path(root_dir).resolve()
        if not root.exists() or not root.is_dir():
            return DeadCodeScanReport()

        python_files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
            for f in filenames:
                if f.endswith(".py"):
                    python_files.append(Path(dirpath) / f)

        if not python_files:
            return DeadCodeScanReport()

        defined_symbols: dict[str, list[tuple[Path, int, int, bool]]] = {}
        all_text_content: list[str] = []

        for p in python_files:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                all_text_content.append(content)
                tree = ast.parse(content, filename=str(p))
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        sym_name = node.name
                        is_private = sym_name.startswith("_") and not (
                            sym_name.startswith("__") and sym_name.endswith("__")
                        )
                        end_lineno = getattr(node, "end_lineno", node.lineno)
                        defined_symbols.setdefault(sym_name, []).append(
                            (p, node.lineno, end_lineno, is_private)
                        )
            except Exception:
                continue

        # Aggregated occurrences across the codebase
        combined_text = "\n".join(all_text_content)

        candidates: list[DeadCodeCandidate] = []
        total_cut = 0

        for sym_name, occurrences in defined_symbols.items():
            if sym_name in ("main", "setUp", "tearDown", "test_"):
                continue
            
            # Count total mentions in source text
            count = combined_text.count(sym_name)
            def_count = len(occurrences)

            # If symbol occurs only at its definition point(s), it is likely unreferenced
            if count <= def_count:
                for path, start, end, is_priv in occurrences:
                    rel_path = str(path.relative_to(root))
                    lines_count = max(1, end - start + 1)
                    risk = SlimmingRiskLevel.SAFE if is_priv else SlimmingRiskLevel.MODERATE
                    reason = (
                        f"Private symbol '{sym_name}' defined but never referenced"
                        if is_priv
                        else f"Public symbol '{sym_name}' has 0 external references in workspace"
                    )
                    candidates.append(
                        DeadCodeCandidate(
                            file_path=rel_path,
                            symbol_name=sym_name,
                            line_start=start,
                            line_end=end,
                            risk_level=risk,
                            reason=reason,
                            estimated_lines_cut=lines_count,
                        )
                    )
                    total_cut += lines_count

        return DeadCodeScanReport(
            candidates=tuple(candidates),
            total_estimated_lines_cut=total_cut,
            scanned_files_count=len(python_files),
        )
