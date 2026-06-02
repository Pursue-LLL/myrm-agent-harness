"""PTC Verifier

Performs static analysis on Python code embedded within bash commands
to extract MCP intent and arguments (e.g., path parameters) before execution.
This enables fine-grained Path Policy enforcement and Fast-Path Auto-Approve for PTC calls.

[INPUT]
- skills.mcp.python_extractor::extract_python_from_bash (POS: Unified Python extraction with quote-aware parsing)

[OUTPUT]
- PTCArgumentValue: Type alias for argument values extracted from PTC scripts.
- extract_ptc_intent: Extract MCP skill/tool intent and arguments from a bash command.

[POS]
AST-based static analysis for PTC scripts. Extracts MCP intent and enables
Fast-Path Auto-Approve for read-only tools while preventing RCE bypass.
"""

from __future__ import annotations

import ast

from myrm_agent_harness.agent.skills.mcp.python_extractor import extract_python_from_bash

PTCArgumentValue = str | int | float | bool | list[object] | dict[str, object] | None

# Strict whitelist of AST node types allowed in a "pure" PTC script.
# Any other node (like For, While, If, Try, With, Import, Attribute, etc.)
# will disqualify the script from Fast-Path Auto-Approve.
_SAFE_NODE_TYPES = {
    ast.Module,
    ast.ImportFrom,
    ast.alias,
    ast.Assign,
    ast.Expr,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Call,
    ast.keyword,
    ast.Constant,
    ast.Dict,
    ast.List,
    ast.Tuple,
    ast.Set,
}

_SAFE_BUILTINS = {
    "print", "len", "str", "int", "float", "bool", "dict", "list", "set", "tuple"
}


def _verify_pure_ptc(tree: ast.Module) -> bool:
    """Ensure the Python code is a pure PTC script without malicious payloads.

    Prevents RCE vulnerabilities where malicious Python code is injected alongside
    a safe MCP tool call to bypass the Approval Gate.
    """
    allowed_calls = set(_SAFE_BUILTINS)

    for node in ast.walk(tree):
        # 1. Ensure node type is explicitly whitelisted
        if type(node) not in _SAFE_NODE_TYPES:
            return False

        # 2. Check ImportFrom statements (only allow skills/tools imports)
        if isinstance(node, ast.ImportFrom):
            if not node.module:
                return False
            # Allow: "from skills.xxx import yyy", "from xxx_skill import yyy", "from tools.xxx import yyy"
            if not (node.module.startswith("skills.") or node.module.startswith("tools.") or node.module.endswith("_skill")):
                return False
            # Register imported names as allowed functions
            for alias in node.names:
                allowed_calls.add(alias.name)

        # 3. Check Call nodes (only allow calling imported tools or safe builtins)
        if isinstance(node, ast.Call):
            # We strictly disallow calling methods on objects (e.g., os.system, subprocess.run)
            # because ast.Attribute is not in _SAFE_NODE_TYPES.
            if not isinstance(node.func, ast.Name):
                return False
            if node.func.id not in allowed_calls:
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

    # Pass 1: Find the import statement to identify skill and tool
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            # Check if it looks like a skill module
            if parts[-1].endswith("_skill"):
                skill_name = parts[-1]
                if node.names:
                    func_name = node.names[0].name
                    if func_name.startswith("_") and func_name != "_":
                        tool_name = func_name[1:]
                    else:
                        tool_name = func_name
                break

    if not skill_name or not tool_name or not func_name:
        return None

    # Pass 2: Find the function call matching the imported tool name
    arguments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
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
