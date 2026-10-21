"""PTC Verifier

Performs static analysis on Python code embedded within bash commands
to extract MCP intent and arguments (e.g., path parameters) before execution.
This enables fine-grained Path Policy enforcement and Fast-Path Auto-Approve for PTC calls.

[INPUT]
- toolkits.code_execution.python_extractor::extract_python_from_bash (POS: Unified Python extraction with quote-aware parsing)

[OUTPUT]
- PTCArgumentValue: Type alias for argument values extracted from PTC scripts.
- extract_ptc_intent: Extract MCP skill/tool intent and arguments from a bash command.

[POS]
AST-based static analysis for PTC scripts. Extracts MCP intent and enables
Fast-Path Auto-Approve for read-only tools while preventing RCE bypass.
"""

from __future__ import annotations

import ast

from myrm_agent_harness.toolkits.code_execution.python_extractor import extract_python_from_bash

PTCArgumentValue = str | int | float | bool | list[object] | dict[str, object] | None

# System modules that must not be imported in a pure PTC MCP script.
# Any script importing these modules will fall back to full human approval (PermissionAction.ASK).
_DANGEROUS_MODULES = frozenset({
    "os",
    "subprocess",
    "sys",
    "socket",
    "shutil",
    "ctypes",
    "pty",
    "builtins",
    "code",
    "codeop",
    "posix",
    "nt",
    "importlib",
    "http.client",
    "urllib.request",
    "ftplib",
    "telnetlib",
    "smtplib",
})

# Dangerous built-in function names that execute arbitrary code or bypass sandboxes.
_DANGEROUS_CALLS = frozenset({
    "eval",
    "exec",
    "__import__",
    "open",
    "compile",
    "breakpoint",
    "globals",
    "locals",
    "input",
})

# Safe standard library modules permitted in scripts alongside skills/tools.
_SAFE_STDLIB_MODULES = frozenset({
    "json",
    "math",
    "re",
    "datetime",
    "typing",
    "collections",
    "itertools",
    "functools",
    "time",
    "random",
})


def _verify_pure_ptc(tree: ast.Module) -> bool:
    """Ensure the Python code is a pure PTC script without malicious payloads.

    Prevents RCE vulnerabilities where malicious Python code is injected alongside
    a safe MCP tool call to bypass the Approval Gate.
    Allows standard control flow (for, while, if, try, with) and data manipulation
    while blocking direct OS/network escape attempts.
    """
    for node in ast.walk(tree):
        # 1. Check imports: only allow safe stdlib modules and skills/tools modules
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root not in _SAFE_STDLIB_MODULES and not (
                    alias.name.startswith("skills.")
                    or alias.name.startswith("tools.")
                    or alias.name.endswith("_skill")
                ):
                    return False
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if not (
                    node.module.startswith("skills.")
                    or node.module.startswith("tools.")
                    or node.module.endswith("_skill")
                    or mod_root in _SAFE_STDLIB_MODULES
                ):
                    return False
            else:
                return False

        # 2. Check function/method calls: block dangerous builtins and dangerous attribute calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _DANGEROUS_CALLS:
                    return False
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id in _DANGEROUS_MODULES:
                    return False
                if node.func.attr in _DANGEROUS_CALLS:
                    return False

    return True


def extract_ptc_intent(command: str) -> tuple[str, str, dict[str, PTCArgumentValue]] | None:
    """Extract MCP skill/tool intent and arguments from a bash command string.

    Args:
        command: The bash command string containing a Python script.

    Returns:
        tuple of (skill_name, tool_name, arguments) if found and safe, else None
    """
    python_code = extract_python_from_bash(command)
    if not python_code:
        return None

    try:
        tree = ast.parse(python_code)
    except SyntaxError:
        return None

    # CRITICAL: Validate that the script contains NO dangerous statements.
    # If the validation fails, we return None and let it fall back to standard
    # full approval flow (preventing Auto-Approve of malicious code).
    if not _verify_pure_ptc(tree):
        return None

    skill_name = None
    tool_name = None
    func_name = None
    func_map: dict[str, tuple[str, str]] = {}  # call_id -> (skill_name, tool_name)

    # Pass 1: Find the import statement to identify skill and tool
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            # Check if it looks like a skill module
            if parts[-1].endswith("_skill"):
                s_name = parts[-1]
                for alias in node.names:
                    raw_fn = alias.name
                    t_name = raw_fn[1:] if raw_fn.startswith("_") and raw_fn != "_" else raw_fn
                    call_id = alias.asname or alias.name
                    func_map[call_id] = (s_name, t_name)
                    if skill_name is None:
                        skill_name = s_name
                        tool_name = t_name
                        func_name = call_id

    if not skill_name or not tool_name or not func_name:
        return None

    # Pass 2: Find the function call matching any imported tool
    arguments: dict[str, PTCArgumentValue] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in func_map:
            s_name, t_name = func_map[node.func.id]
            skill_name, tool_name = s_name, t_name
            # Extract kwargs
            for kw in node.keywords:
                if kw.arg:
                    try:
                        # Safely evaluate literals
                        if isinstance(kw.value, ast.Constant):
                            arguments[kw.arg] = kw.value.value
                        elif isinstance(kw.value, (ast.List, ast.Dict, ast.Tuple, ast.Set)):
                            arguments[kw.arg] = ast.literal_eval(kw.value)
                    except Exception:
                        # Ignore non-literals or unparseable structures
                        pass
            break

    return skill_name, tool_name, arguments
