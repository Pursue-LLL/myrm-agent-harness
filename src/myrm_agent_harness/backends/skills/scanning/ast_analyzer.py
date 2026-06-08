"""Python AST-based security analysis for skill code.

Detects dangerous patterns that regex cannot reliably catch:
- eval/exec with dynamic arguments
- __import__ / importlib.import_module with non-literal module names
- subprocess calls with shell=True
- os.system / os.popen calls
- pickle.loads / yaml.load (unsafe deserialization)
- getattr with dynamic attribute names (reflection)
- open() with write modes
- compile() with dynamic source

Operates on a "detect-only" principle — reports findings but does not modify code.

[INPUT]
- (none)

[OUTPUT]
- AstScanFinding: single AST-level finding
- analyze_python_ast(): analyze Python source code via AST
- is_python_file(): check if a file path is a Python file

[POS]
AST-level security analysis for Python skill code. Complements regex patterns
with structural analysis that cannot be bypassed by string obfuscation.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PYTHON_EXTENSIONS = frozenset({".py", ".pyw", ".pyi"})


@dataclass(frozen=True, slots=True)
class AstScanFinding:
    """A single finding from AST analysis."""

    threat_type: str
    severity: str  # "critical", "high", "medium", "low"
    description: str
    line_number: int | None = None
    code_fragment: str = ""


def is_python_file(file_path: str) -> bool:
    """Check if a file path has a Python extension."""
    return Path(file_path).suffix.lower() in _PYTHON_EXTENSIONS


def analyze_python_ast(source: str, file_label: str = "") -> list[AstScanFinding]:
    """Analyze Python source code via AST for security threats.

    Args:
        source: Python source code string
        file_label: Optional label for error messages

    Returns:
        List of findings (empty if clean)
    """
    if not source or not source.strip():
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            AstScanFinding(
                threat_type="ast_parse_error",
                severity="info",
                description=f"Syntax error in {file_label or 'source'}: {exc.msg}",
                line_number=exc.lineno,
            )
        ]

    visitor = _SecurityVisitor()
    visitor.visit(tree)
    return visitor.findings


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor that detects dangerous patterns."""

    __slots__ = ("findings",)

    def __init__(self) -> None:
        self.findings: list[AstScanFinding] = []

    def _add(self, threat_type: str, severity: str, description: str, node: ast.AST) -> None:
        self.findings.append(
            AstScanFinding(
                threat_type=threat_type,
                severity=severity,
                description=description,
                line_number=getattr(node, "lineno", None),
            )
        )

    # -- Dangerous built-in calls --

    def visit_Call(self, node: ast.Call) -> None:
        func_name = _resolve_call_name(node.func)

        if func_name in ("eval", "exec"):
            if not _is_literal_string(node.args):
                self._add(
                    "code_injection",
                    "critical",
                    f"Dynamic code execution: {func_name}() with non-literal argument",
                    node,
                )
            else:
                self._add(
                    "code_injection",
                    "high",
                    f"Code execution: {func_name}() call detected",
                    node,
                )

        elif func_name == "__import__":
            if not _is_literal_string(node.args):
                self._add(
                    "reflection",
                    "high",
                    "Dynamic import: __import__() with non-literal module name",
                    node,
                )

        elif func_name in ("os.system", "os.popen"):
            self._add(
                "command_injection",
                "critical",
                f"Shell command execution: {func_name}()",
                node,
            )

        elif func_name in ("subprocess.call", "subprocess.run", "subprocess.Popen"):
            if _has_shell_true(node):
                self._add(
                    "command_injection",
                    "critical",
                    f"Shell subprocess: {func_name}(shell=True)",
                    node,
                )
            elif _has_dynamic_args(node):
                self._add(
                    "command_injection",
                    "high",
                    f"Subprocess with dynamic arguments: {func_name}()",
                    node,
                )

        elif func_name == "subprocess.check_output":
            if _has_shell_true(node):
                self._add(
                    "command_injection",
                    "critical",
                    "Shell subprocess: subprocess.check_output(shell=True)",
                    node,
                )

        elif func_name == "compile":
            if len(node.args) >= 1 and not _is_literal_string([node.args[0]]):
                self._add(
                    "code_injection",
                    "high",
                    "Dynamic code compilation: compile() with non-literal source",
                    node,
                )

        elif func_name == "pickle.loads":
            self._add(
                "deserialization",
                "high",
                "Unsafe deserialization: pickle.loads()",
                node,
            )

        elif func_name == "pickle.load":
            self._add(
                "deserialization",
                "medium",
                "Deserialization: pickle.load() — ensure trusted input",
                node,
            )

        elif func_name == "yaml.load":
            if not _has_safe_loader(node):
                self._add(
                    "deserialization",
                    "high",
                    "Unsafe YAML loading: yaml.load() without SafeLoader",
                    node,
                )

        elif func_name == "yaml.full_load":
            self._add(
                "deserialization",
                "high",
                "Unsafe YAML loading: yaml.full_load() can execute arbitrary Python",
                node,
            )

        elif func_name == "getattr" and len(node.args) >= 2:
            if not _is_literal_string([node.args[1]]):
                self._add(
                    "reflection",
                    "medium",
                    "Dynamic attribute access: getattr() with non-literal attribute name",
                    node,
                )

        elif func_name in ("globals", "locals", "vars"):
            self._add(
                "reflection",
                "medium",
                f"Introspection: {func_name}() exposes internal state",
                node,
            )

        elif func_name == "dict" and len(node.args) == 1:
            arg = node.args[0]
            if (
                isinstance(arg, ast.Attribute)
                and arg.attr == "environ"
                and isinstance(arg.value, ast.Name)
                and arg.value.id == "os"
            ):
                self._add(
                    "data_exfiltration",
                    "high",
                    "Bulk environment variable access: dict(os.environ)",
                    node,
                )

        elif func_name == "open" and len(node.args) >= 2:
            mode = _extract_string_literal(node.args[1])
            if mode and any(c in mode for c in ("w", "a", "x", "+")):
                self._add(
                    "filesystem_access",
                    "low",
                    f"File write: open() with mode '{mode}'",
                    node,
                )

        self.generic_visit(node)

    # -- Dangerous attribute access patterns --

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Detect ctypes usage (direct memory access)
        if isinstance(node.value, ast.Name) and node.value.id == "ctypes":
            self._add(
                "process_operation",
                "high",
                "Direct memory access via ctypes",
                node,
            )

        # Detect os.environ bulk access patterns
        if node.attr in ("items", "values", "copy", "keys") and isinstance(node.value, ast.Attribute):
            inner = node.value
            if inner.attr == "environ" and isinstance(inner.value, ast.Name) and inner.value.id == "os":
                self._add(
                    "data_exfiltration",
                    "high",
                    f"Bulk environment variable access: os.environ.{node.attr}()",
                    node,
                )

        self.generic_visit(node)

    # -- Dangerous imports --

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module = alias.name
            if module in _DANGEROUS_MODULES:
                severity = _DANGEROUS_MODULES[module]
                self._add(
                    "dangerous_import",
                    severity,
                    f"Dangerous module import: {module}",
                    node,
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module in _DANGEROUS_MODULES:
            severity = _DANGEROUS_MODULES[module]
            self._add(
                "dangerous_import",
                severity,
                f"Dangerous module import: from {module} import ...",
                node,
            )
        elif module.startswith("ctypes"):
            self._add(
                "process_operation",
                "high",
                f"Direct memory access via ctypes: from {module} import ...",
                node,
            )
        self.generic_visit(node)


_DANGEROUS_MODULES: dict[str, str] = {
    "ctypes": "high",
    "shlex": "low",  # Used to bypass shell escaping
    "signal": "medium",
    "_thread": "medium",
    "threading": "low",
}


def _resolve_call_name(func: ast.expr) -> str:
    """Resolve a function call node to a dotted name string."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _is_literal_string(args: list[ast.expr]) -> bool:
    """Check if all arguments are literal strings (constant values)."""
    if not args:
        return True
    return all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in args)


def _extract_string_literal(node: ast.expr) -> str | None:
    """Extract a string literal from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _has_shell_true(node: ast.Call) -> bool:
    """Check if a function call has shell=True keyword argument."""
    for kw in node.keywords:
        if kw.arg == "shell":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def _has_dynamic_args(node: ast.Call) -> bool:
    """Check if a subprocess call has dynamic (non-literal) arguments."""
    for arg in node.args:
        if isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                if not isinstance(elt, ast.Constant):
                    return True
        elif isinstance(arg, ast.Constant):
            continue
        else:
            return True
    return False


def _has_safe_loader(node: ast.Call) -> bool:
    """Check if yaml.load() uses SafeLoader."""
    for kw in node.keywords:
        if kw.arg == "Loader":
            if isinstance(kw.value, ast.Attribute):
                return kw.value.attr == "SafeLoader"
            if isinstance(kw.value, ast.Name):
                return kw.value.id == "SafeLoader"
    # Also check positional second argument
    if len(node.args) >= 2:
        arg = node.args[1]
        if isinstance(arg, ast.Attribute):
            return arg.attr == "SafeLoader"
        if isinstance(arg, ast.Name):
            return arg.id == "SafeLoader"
    return False


