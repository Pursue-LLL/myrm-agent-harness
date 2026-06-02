"""Core scanning engine for tool-registry consistency enforcement.

Detects every tool exposed to LangChain-compatible agents and cross-references
them against the harness `_TOOL_LAYERS` (extended at runtime by the server
bootstrap module). Three discovery modes are implemented:

1. `@tool("xxx")` / `@tool` decorators on async/sync functions.
2. `BaseTool` subclasses declaring `name: str = "xxx"` or `name = "xxx"`.
3. Middleware mutating tool name after construction
   (`xxx_tool.name = "yyy"`).

Output is a `ScanReport` dataclass that the CLI consumes for diagnostics,
auto-fix proposals, and documentation generation.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from scripts.tool_registry_config import (
    BOOTSTRAP_FILE_PATHS,
    CROSS_MODULE_CONSTANTS,
    EXCLUDED_DIRS,
    HARNESS_SRC,
    REPO_ROOT,
    SCAN_ROOTS,
    SERVER_SRC,
    is_test_path,
)
from scripts.tool_registry_models import ScanReport, ToolDeclaration


def _iter_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if is_test_path(path):
            continue
        files.append(path)
    return files


def _parse(path: Path) -> ast.Module | None:
    """Parse a Python file. Syntax errors are surfaced so they're not silently
    masked — `@tool` declarations inside a broken file would otherwise be missed.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        print(f"WARN: syntax error in {path}: {exc}", file=sys.stderr)
        return None
    except (UnicodeDecodeError, OSError):
        return None


def _decorator_is_tool(decorator: ast.expr) -> bool:
    """Return True if a decorator expression is `@tool` or `@tool(...)`."""
    if isinstance(decorator, ast.Name):
        return decorator.id == "tool"
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Name) and func.id == "tool":
            return True
    return False


def _build_string_constants(tree: ast.Module) -> dict[str, str]:
    """Index module-level string constants for decorator-name resolution.

    Enables `@tool(TOOL_NAME)` / `@tool(SOME_CONSTANT)` to be statically resolved
    when the constant is declared in the same module. Cross-module constants
    fall back to `INTERNAL_CONSTANT_VALUES` (see config).
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    constants[target.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.target.id] = node.value.value
    return constants


def _tool_name_from_decorator(
    decorator: ast.expr, func_name: str, constants: dict[str, str]
) -> str | None:
    """Extract the tool name. Resolves string literals and module-level constants.

    Falls back to the function name when neither literal nor known constant is present.
    """
    if isinstance(decorator, ast.Name):
        return func_name
    if isinstance(decorator, ast.Call):
        for arg in decorator.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
            if isinstance(arg, ast.Name):
                resolved = constants.get(arg.id) or CROSS_MODULE_CONSTANTS.get(arg.id)
                if resolved is not None:
                    return resolved
        return func_name
    return None


def _collect_decorated_tools(tree: ast.Module, path: Path) -> list[ToolDeclaration]:
    """Walk every function/class node to catch @tool decorators at any nesting depth.

    Many LangChain tool definitions live inside factory closures, so a strict
    top-level scan misses them. `ast.walk` covers nested function definitions.
    Also discovers top-level `xxx_tool = tool("name")(func)` assignments.
    """
    constants = _build_string_constants(tree)
    decls: list[ToolDeclaration] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if not _decorator_is_tool(decorator):
                    continue
                name = _tool_name_from_decorator(decorator, node.name, constants)
                if name is None:
                    continue
                decls.append(ToolDeclaration(name=name, kind="decorator", file=path, line=node.lineno))
        elif isinstance(node, ast.ClassDef):
            decls.extend(_collect_basetool_subclass(node, path))
    decls.extend(_collect_module_tool_assignments(tree, path, constants))
    return decls


def _collect_module_tool_assignments(
    tree: ast.Module, path: Path, constants: dict[str, str]
) -> list[ToolDeclaration]:
    """Detect `xxx_tool = tool("name")(func)` module-level constructions."""
    decls: list[ToolDeclaration] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        outer = node.value
        if not isinstance(outer.func, ast.Call):
            continue
        inner = outer.func
        if not (isinstance(inner.func, ast.Name) and inner.func.id == "tool"):
            continue
        name: str | None = None
        for arg in inner.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
                break
            if isinstance(arg, ast.Name):
                name = constants.get(arg.id) or CROSS_MODULE_CONSTANTS.get(arg.id)
                if name is not None:
                    break
        if name is not None:
            decls.append(ToolDeclaration(name=name, kind="assignment", file=path, line=node.lineno))
    return decls


def _collect_basetool_subclass(node: ast.ClassDef, path: Path) -> list[ToolDeclaration]:
    """Detect `class XxxTool(BaseTool): name: str = "yyy"` patterns."""
    base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
    if "BaseTool" not in base_names:
        return []
    for body_node in node.body:
        if (
            isinstance(body_node, ast.AnnAssign)
            and isinstance(body_node.target, ast.Name)
            and body_node.target.id == "name"
            and isinstance(body_node.value, ast.Constant)
            and isinstance(body_node.value.value, str)
        ):
            return [ToolDeclaration(name=body_node.value.value, kind="basetool", file=path, line=body_node.lineno, container=node.name)]
        if isinstance(body_node, ast.Assign):
            for target in body_node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "name"
                    and isinstance(body_node.value, ast.Constant)
                    and isinstance(body_node.value.value, str)
                ):
                    return [ToolDeclaration(name=body_node.value.value, kind="basetool", file=path, line=body_node.lineno, container=node.name)]
    return []


def _collect_middleware_renames(tree: ast.Module, path: Path) -> list[ToolDeclaration]:
    """Detect `xxx_tool.name = "yyy"` and `tool.name = "yyy"` patterns."""
    decls: list[ToolDeclaration] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == "name":
                decls.append(ToolDeclaration(name=node.value.value, kind="rename", file=path, line=node.lineno))
                break
    return decls


def _collect_factories(tree: ast.Module, path: Path) -> dict[str, Path]:
    """Locate functions named `create_*_tools` / `create_*_tool` returning tools."""
    factories: dict[str, Path] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name.startswith("create_") and (node.name.endswith("_tools") or node.name.endswith("_tool"))
        ):
            factories[node.name] = path
    return factories


def _count_call_sites(factory_names: set[str], scan_roots: tuple[Path, ...]) -> dict[str, list[Path]]:
    """Find direct call sites by static text search; bootstrap files excluded."""
    call_sites: dict[str, list[Path]] = {f: [] for f in factory_names}
    bootstrap_paths = {path.resolve() for path in BOOTSTRAP_FILE_PATHS}
    for root in scan_roots:
        for path in _iter_python_files(root):
            if path.resolve() in bootstrap_paths:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for factory in factory_names:
                if f"{factory}(" not in content:
                    continue
                module_decl_line = f"def {factory}("
                if module_decl_line in content and content.count(f"{factory}(") == content.count(module_decl_line):
                    continue
                call_sites[factory].append(path)
    return call_sites


def load_registered_layers() -> dict[str, str]:
    """Return the union of harness static `_TOOL_LAYERS` and server bootstrap,
    keyed by tool name, valued by layer name ("CORE" | "COMMON" | "EXTENDED").

    The server bootstrap is parsed statically (AST) so callers do not need to
    import the server package — useful for CI environments where only the
    harness has its dependencies installed.
    """
    sys.path.insert(0, str(HARNESS_SRC.parent))
    try:
        from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

        layers: dict[str, str] = {name: layer.name for name, layer in _TOOL_LAYERS.items()}
    finally:
        if str(HARNESS_SRC.parent) in sys.path:
            sys.path.remove(str(HARNESS_SRC.parent))

    bootstrap = SERVER_SRC / "ai_agents" / "general_agent" / "tools" / "_tool_layer_bootstrap.py"
    if bootstrap.exists():
        tree = _parse(bootstrap)
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                elif isinstance(node, ast.Assign):
                    targets = node.targets
                else:
                    continue
                value = node.value
                if not isinstance(value, ast.Dict):
                    continue
                for target in targets:
                    if not (isinstance(target, ast.Name) and target.id == "_SERVER_TOOL_LAYERS"):
                        continue
                    for key, val in zip(value.keys, value.values, strict=False):
                        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                            continue
                        layer_name = _resolve_layer_literal(val)
                        if layer_name is not None:
                            layers[key.value] = layer_name
    return layers


def _resolve_layer_literal(node: ast.expr) -> str | None:
    """Resolve `ToolLayer.CORE` style attribute references to the layer name."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ToolLayer":
        return node.attr
    return None


def load_registered_names() -> set[str]:
    """Backward-compatible name-set view over `load_registered_layers()`."""
    return set(load_registered_layers().keys())


def scan() -> ScanReport:
    """Execute a full scan across all configured roots."""
    report = ScanReport()
    report.registered_names = load_registered_names()

    for root in SCAN_ROOTS:
        for path in _iter_python_files(root):
            report.files_scanned += 1
            tree = _parse(path)
            if tree is None:
                continue
            report.declarations.extend(_collect_decorated_tools(tree, path))
            report.declarations.extend(_collect_middleware_renames(tree, path))
            report.factories.update(_collect_factories(tree, path))

    report.factory_call_sites = _count_call_sites(set(report.factories.keys()), SCAN_ROOTS)
    return report


def get_changed_python_files(scan_roots: tuple[Path, ...]) -> list[Path] | None:
    """Return Python files changed in git (staged + unstaged)."""
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if staged.returncode != 0 or unstaged.returncode != 0:
        return None

    files = set(staged.stdout.strip().split("\n")) | set(unstaged.stdout.strip().split("\n"))
    files.discard("")
    rel_roots = [r.relative_to(REPO_ROOT).as_posix() + "/" for r in scan_roots if str(r).startswith(str(REPO_ROOT))]
    return [REPO_ROOT / f for f in files if f.endswith(".py") and any(f.startswith(prefix) for prefix in rel_roots)]


__all__ = [
    "ScanReport",
    "ToolDeclaration",
    "get_changed_python_files",
    "load_registered_layers",
    "load_registered_names",
    "scan",
]
# ScanReport / ToolDeclaration are re-exported from scripts.tool_registry_models
# so existing imports of `tool_registry_engine` keep working.
