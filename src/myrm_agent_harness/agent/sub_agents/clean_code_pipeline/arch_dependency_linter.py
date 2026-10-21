"""Static Architecture Dependency Linter and DIP Auto-Refactoring Advisor (Item 62).

[INPUT]
- Python module source code strings or file paths.
- Declared DependencyRule specifications defining allowed layer dependency directions.

[OUTPUT]
- LinterResult with detected ArchitectureViolation instances and DIP refactoring guidance.

[POS]
- Harness architectural firewall enforcing unidirectional layer dependencies and preventing pollution.
"""

from __future__ import annotations

import ast
import logging
from collections import defaultdict
from typing import Final

from .types import (
    ArchitectureViolation,
    DependencyRule,
    LinterResult,
    ViolationType,
)

logger: Final = logging.getLogger(__name__)

# Standard architectural layers in Clean Architecture / Hexagonal Architecture
DEFAULT_LAYER_RULES: Final[list[DependencyRule]] = [
    # UI/API layer may only depend on Application layer and DTOs
    DependencyRule(source_layer="ui", allowed_target_layers=["application", "schemas", "domain"]),
    # Application layer coordinates use cases; may only depend on Domain
    DependencyRule(source_layer="application", allowed_target_layers=["domain", "schemas"]),
    # Domain layer is pure enterprise logic; must NEVER depend on UI, Application, or Infra!
    DependencyRule(source_layer="domain", allowed_target_layers=["domain", "schemas"]),
    # Infrastructure implements interfaces; may depend on Domain
    DependencyRule(source_layer="infrastructure", allowed_target_layers=["domain", "schemas"]),
]


class ArchitectureDependencyLinter:
    """Enforces unidirectional architectural layers and detects invalid imports via AST."""

    def __init__(self, rules: list[DependencyRule] | None = None) -> None:
        self._rules: dict[str, set[str]] = {}
        target_rules = rules if rules is not None else DEFAULT_LAYER_RULES
        for r in target_rules:
            self._rules[r.source_layer.lower()] = {t.lower() for t in r.allowed_target_layers}

    def _determine_layer(self, module_path: str) -> str:
        """Heuristically assign a module path to an architectural layer."""
        normalized = module_path.lower().replace(".", "/").replace("\\", "/")
        parts = [p for p in normalized.split("/") if p]

        for part in parts:
            if part in {"ui", "api", "views", "controllers", "routers"}:
                return "ui"
            if part in {"application", "services", "use_cases"}:
                return "application"
            if part in {"domain", "core", "models", "entities"}:
                return "domain"
            if part in {"infrastructure", "infra", "adapters", "persistence", "db"}:
                return "infrastructure"
            if part in {"schemas", "dto", "types"}:
                return "schemas"

        return "unknown"

    def extract_imports(self, code_content: str) -> list[str]:
        """Parse source code via AST and extract all imported module targets."""
        imported_targets: list[str] = []
        try:
            tree = ast.parse(code_content)
        except SyntaxError as err:
            logger.warning("Failed to parse code snippet for AST import extraction: %s", err)
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_targets.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_targets.append(node.module)

        return imported_targets

    def lint_module_code(
        self,
        source_module_path: str,
        code_content: str,
    ) -> LinterResult:
        """Lint a single module source against configured architectural layer rules."""
        imports = self.extract_imports(code_content)
        source_layer = self._determine_layer(source_module_path)
        violations: list[ArchitectureViolation] = []
        edges: list[tuple[str, str]] = []

        allowed_targets = self._rules.get(source_layer, set())

        for target_import in imports:
            target_layer = self._determine_layer(target_import)
            edges.append((source_module_path, target_import))

            # Skip same-layer dependencies and unknown non-governed modules (e.g. stdlib / 3rd party)
            if target_layer in {source_layer, "unknown"}:
                continue

            # Core Domain rule: Domain must never depend on outer layers!
            if source_layer == "domain" and target_layer in {"ui", "application", "infrastructure"}:
                violations.append(
                    ArchitectureViolation(
                        source_module=source_module_path,
                        target_module=target_import,
                        violation_type=ViolationType.INVERTED_DEPENDENCY,
                        rule_description=f"Domain layer '{source_module_path}' cannot import outer layer '{target_layer}' ({target_import}).",
                        remediation_suggestion=(
                            f"Apply DIP: declare an abstract interface/Protocol in '{source_module_path}' "
                            f"and implement it in '{target_import}' or use dependency injection."
                        ),
                    )
                )
                continue

            # Check general allowed targets whitelist
            if allowed_targets and target_layer not in allowed_targets:
                violations.append(
                    ArchitectureViolation(
                        source_module=source_module_path,
                        target_module=target_import,
                        violation_type=ViolationType.LAYER_BYPASS,
                        rule_description=f"Layer '{source_layer}' is not permitted to directly depend on layer '{target_layer}'.",
                        remediation_suggestion="Route communication via the Application/Service layer instead of bypassing boundaries.",
                    )
                )

        return LinterResult(
            is_valid=len(violations) == 0,
            violations=violations,
            scanned_files_count=1,
            dependency_edges=edges,
        )

    def detect_circular_dependencies(
        self,
        module_dependency_graph: dict[str, list[str]],
    ) -> list[ArchitectureViolation]:
        """Run cycle detection across multi-module dependency graphs."""
        visited: set[str] = set()
        rec_stack: set[str] = set()
        violations: list[ArchitectureViolation] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in module_dependency_graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, [*path, neighbor])
                elif neighbor in rec_stack:
                    cycle_path = " -> ".join([*path, neighbor])
                    violations.append(
                        ArchitectureViolation(
                            source_module=node,
                            target_module=neighbor,
                            violation_type=ViolationType.CIRCULAR_DEPENDENCY,
                            rule_description=f"Circular dependency detected: {cycle_path}",
                            remediation_suggestion="Extract shared abstractions or event-driven decoupled callbacks to break cycle.",
                        )
                    )

            rec_stack.remove(node)

        for mod in list(module_dependency_graph.keys()):
            if mod not in visited:
                dfs(mod, [mod])

        return violations

    def _normalize_module_id(self, path_or_module: str) -> str:
        """Normalize file paths and import strings into dot-separated module identities."""
        cleaned = path_or_module.replace("\\", "/").strip("./")
        if cleaned.endswith(".py"):
            cleaned = cleaned[:-3]
        return cleaned.replace("/", ".")

    def lint_project_modules(
        self,
        modules: dict[str, str],
    ) -> LinterResult:
        """Lint an entire set of modules for layer violations and circular dependencies."""
        all_violations: list[ArchitectureViolation] = []
        all_edges: list[tuple[str, str]] = []
        graph: dict[str, list[str]] = defaultdict(list)

        for mod_path, code in modules.items():
            result = self.lint_module_code(mod_path, code)
            all_violations.extend(result.violations)
            all_edges.extend(result.dependency_edges)
            norm_src = self._normalize_module_id(mod_path)
            for _, tgt in result.dependency_edges:
                norm_tgt = self._normalize_module_id(tgt)
                graph[norm_src].append(norm_tgt)

        # Detect circular dependencies
        cycle_violations = self.detect_circular_dependencies(graph)
        all_violations.extend(cycle_violations)

        return LinterResult(
            is_valid=len(all_violations) == 0,
            violations=all_violations,
            scanned_files_count=len(modules),
            dependency_edges=all_edges,
        )
