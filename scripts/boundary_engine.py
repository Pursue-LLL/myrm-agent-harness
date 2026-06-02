"""Core detection engine for architecture boundary enforcement.

Provides AST-based import analysis including static imports,
dynamic imports (importlib, __import__), exec/eval, and f-string detection.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from scripts.boundary_config import (
    ALLOWED_FRAMEWORK_PREFIXES,
    ALLOWED_PATHS,
    BANNED_PREFIXES,
)

_repo_root = Path(__file__).parent.parent


def get_changed_harness_files(harness_root: Path) -> list[Path] | None:
    """Get Python files changed in the harness directory via git.

    Checks both staged and unstaged changes. Returns None if git is
    unavailable or not in a git repository (caller should fall back to full scan).
    """
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if staged.returncode != 0 or unstaged.returncode != 0:
        return None

    all_files = set(staged.stdout.strip().split("\n")) | set(unstaged.stdout.strip().split("\n"))
    all_files.discard("")

    harness_prefix = str(harness_root.relative_to(_repo_root)) + "/"
    return [_repo_root / f for f in all_files if f.endswith(".py") and f.startswith(harness_prefix)]


def collect_imports(filepath: Path) -> list[tuple[int, str]]:
    """Extract all import statements from a Python file.

    Detects static imports, dynamic imports, exec/eval, and f-string patterns.

    Returns:
        List of (line_number, module_name) tuples.
        Empty list if file cannot be parsed.
    """
    if not filepath.exists():
        print(f"⚠️  File not found: {filepath}", file=sys.stderr)
        return []

    try:
        source = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(f"⚠️  Encoding error in {filepath}: {e}", file=sys.stderr)
        return []
    except PermissionError:
        print(f"⚠️  Permission denied: {filepath}", file=sys.stderr)
        return []
    except OSError as e:
        print(f"⚠️  OS error reading {filepath}: {e}", file=sys.stderr)
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"⚠️  Syntax error in {filepath}:{e.lineno}: {e.msg}", file=sys.stderr)
        return []
    except ValueError as e:
        print(f"⚠️  Parse error in {filepath}: {e}", file=sys.stderr)
        return []

    results: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            results.append((node.lineno, node.module))

    results.extend(_collect_dynamic_imports(tree))
    return results


def _collect_dynamic_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Extract dynamic import calls from AST.

    Detects:
    - importlib.import_module("x") / importlib.import_module(f"prefix.{name}")
    - __import__("x")
    - exec("import x") / eval("__import__('x')")
    """
    results: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "import_module"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
            ):
                results.extend(_extract_import_module_args(node))

        elif isinstance(node.func, ast.Name):
            if node.func.id == "__import__":
                if node.args and isinstance(node.args[0], ast.Constant):
                    module_name = node.args[0].value
                    if isinstance(module_name, str):
                        results.append((node.lineno, module_name))

            elif node.func.id in ("exec", "eval"):
                results.extend(_extract_exec_eval_imports(node))

    return results


def _extract_import_module_args(node: ast.Call) -> list[tuple[int, str]]:
    """Extract module names from importlib.import_module() calls.

    Handles both string literals and f-strings with detectable prefixes.
    """
    if not node.args:
        return []

    arg = node.args[0]

    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [(node.lineno, arg.value)]

    if isinstance(arg, ast.JoinedStr):
        prefix = _extract_fstring_prefix(arg)
        if prefix:
            return [(node.lineno, prefix)]

    return []


def _extract_fstring_prefix(node: ast.JoinedStr) -> str:
    """Extract the leading constant prefix from an f-string.

    For f"app.models.{name}", returns "app.models".
    Returns empty string if no constant prefix found.
    """
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            break
    return "".join(parts).rstrip(".")


def _extract_exec_eval_imports(node: ast.Call) -> list[tuple[int, str]]:
    """Detect import statements hidden inside exec()/eval() calls.

    Only detects string literal arguments containing import keywords.
    """
    if not node.args:
        return []

    arg = node.args[0]
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return []

    code_str = arg.value.strip()
    if "import " not in code_str:
        return []

    try:
        inner_tree = ast.parse(code_str)
    except SyntaxError:
        return []

    results: list[tuple[int, str]] = []
    for inner_node in ast.walk(inner_tree):
        if isinstance(inner_node, ast.Import):
            for alias in inner_node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(inner_node, ast.ImportFrom) and inner_node.module:
            results.append((node.lineno, inner_node.module))

    return results


def is_banned_import(module: str) -> bool:
    """Check if module is a banned business layer import.

    Uses whitelist-first approach: modules in ALLOWED_FRAMEWORK_PREFIXES pass,
    modules in BANNED_PREFIXES or with myrm_ prefix are blocked,
    everything else (stdlib, third-party) is allowed.
    """
    for prefix in ALLOWED_FRAMEWORK_PREFIXES:
        if module == prefix or module.startswith(f"{prefix}."):
            return False

    for prefix in BANNED_PREFIXES:
        if module == prefix or module.startswith(f"{prefix}."):
            return True

    return bool(module.startswith("myrm_") and not module.startswith("myrm_agent_harness"))


def is_allowed_path(filepath: Path, harness_root: Path) -> bool:
    """Check if filepath is in the path whitelist."""
    relative_path = str(filepath.relative_to(harness_root.parent.parent))
    return any(relative_path.startswith(f"{allowed}/") or relative_path == allowed for allowed in ALLOWED_PATHS)


def fix_violations(
    filepath: Path,
    violations: list[tuple[int, str]],
) -> tuple[int, list[str]]:
    """Comment out violation lines in the file.

    Returns:
        Tuple of (fixed_count, fixed_lines)
    """
    if not violations:
        return 0, []

    if not filepath.exists():
        print(f"⚠️  Cannot fix: file not found: {filepath}", file=sys.stderr)
        return 0, []

    try:
        lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, PermissionError, OSError) as e:
        print(f"⚠️  Cannot fix {filepath}: {e}", file=sys.stderr)
        return 0, []

    fixed_lines: list[str] = []
    fixed_count = 0

    violation_lines = {lineno for lineno, _ in violations}

    for idx, line in enumerate(lines, start=1):
        if idx in violation_lines:
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            commented = f"{indent}# BOUNDARY-VIOLATION: {stripped}"
            lines[idx - 1] = commented
            fixed_lines.append(f"  Line {idx}: {stripped.strip()}")
            fixed_count += 1

    try:
        filepath.write_text("".join(lines), encoding="utf-8")
    except (PermissionError, OSError) as e:
        print(f"⚠️  Cannot write to {filepath}: {e}", file=sys.stderr)
        return 0, []

    return fixed_count, fixed_lines


PRIORITY_HIGH_DIRS = ("agent/", "runtime/", "toolkits/")
PRIORITY_LOW_DIRS = ("tests/", "benchmarks/", "scripts/")


def classify_priority(filepath: Path, harness_root: Path) -> str:
    """Classify violation priority based on file location.

    Core framework paths (agent/, runtime/, toolkits/) are HIGH priority.
    Infrastructure/utility paths are MEDIUM.
    Test/script paths are LOW.
    """
    try:
        rel = str(filepath.relative_to(harness_root))
    except ValueError:
        return "MEDIUM"

    if any(rel.startswith(d) for d in PRIORITY_HIGH_DIRS):
        return "HIGH"
    if any(rel.startswith(d) for d in PRIORITY_LOW_DIRS):
        return "LOW"
    return "MEDIUM"


def check_file(
    filepath: Path,
    harness_root: Path,
    fix: bool = False,
) -> tuple[int, list[str]]:
    """Check a single file for boundary violations.

    Returns:
        Tuple of (violation_count, violation_messages)
    """
    if is_allowed_path(filepath, harness_root):
        return 0, []

    violations: list[tuple[int, str]] = []
    for lineno, module in collect_imports(filepath):
        if is_banned_import(module):
            violations.append((lineno, module))

    if not violations:
        return 0, []

    rel_path = filepath.relative_to(harness_root.parent.parent.parent)

    if fix:
        fixed_count, fixed_lines = fix_violations(filepath, violations)
        messages = [
            f"✓ {rel_path}",
            *fixed_lines,
        ]
        return fixed_count, messages

    priority = classify_priority(filepath, harness_root)
    priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[priority]

    messages = []
    for lineno, module in violations:
        msg = f"\n  {priority_icon} [{priority}] {rel_path}:{lineno}\n"
        msg += f"    ❌ Framework layer cannot import: {module}\n"
        msg += "\n"
        msg += "    💡 Fix suggestions:\n"
        msg += "       1. Use dependency injection (pass as parameter)\n"
        msg += "       2. Move code to business layer\n"
        msg += "       3. Extract Protocol to framework\n"
        messages.append(msg)

    return len(violations), messages
