"""Validation helpers for persisted Dynamic Workflow orchestration scripts.

[INPUT]
- None (pure validation utilities)

[OUTPUT]
- validate_orchestration_script, apply_template_args, extract_template_placeholders, validate_template_args, can_skip_plan_confirm

[POS]
Trust and safety guardrails for named workflow template save and pinned rerun paths.
"""

from __future__ import annotations

import ast
import hashlib
import re

_MAX_SCRIPT_BYTES = 256_000
_FORBIDDEN_SNIPPETS = (
    "import subprocess",
    "from subprocess",
    "os.system(",
    "os.popen(",
    "__import__(",
    "eval(",
    "exec(",
)

_SPAWN_CALL_PATTERN = re.compile(r"myrm_tools\.spawn_subagent\s*\(")
_AGENT_TYPE_PATTERN = re.compile(r"""agent_type\s*=\s*["']([^"']+)["']""")
_PLACEHOLDER_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_UNSAFE_TEMPLATE_ARG_CHARS = frozenset("\"\n\r\\'")


def normalize_template_args(template_args: dict[str, str] | None) -> dict[str, str]:
    if not template_args:
        return {}
    return {key: value.strip() for key, value in template_args.items()}


def validate_template_args(
    script_code: str,
    template_args: dict[str, str] | None,
) -> tuple[bool, str | None]:
    """Ensure every `{placeholder}` in the script has a safe, non-empty value."""
    placeholders = extract_template_placeholders(script_code)
    if not placeholders:
        return True, None

    args = normalize_template_args(template_args)
    missing = [key for key in placeholders if not args.get(key)]
    if missing:
        joined = ", ".join(missing)
        return False, f"Missing workflow template placeholder(s): {joined}."

    for key in placeholders:
        value = args[key]
        if any(char in value for char in _UNSAFE_TEMPLATE_ARG_CHARS):
            return False, f"Invalid workflow template argument `{key}`: contains forbidden characters."

    return True, None


def compute_script_hash(script_code: str) -> str:
    return hashlib.sha256(script_code.encode()).hexdigest()


def extract_required_agent_types(script_code: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _AGENT_TYPE_PATTERN.finditer(script_code):
        agent_type = match.group(1).strip()
        if agent_type and agent_type not in seen:
            seen.add(agent_type)
            ordered.append(agent_type)
    return ordered


def validate_orchestration_script(script_code: str) -> tuple[bool, str | None]:
    cleaned = script_code.strip()
    if not cleaned:
        return False, "Script is empty."
    if len(cleaned.encode()) > _MAX_SCRIPT_BYTES:
        return False, f"Script exceeds {_MAX_SCRIPT_BYTES} bytes."
    lowered = cleaned.lower()
    for forbidden in _FORBIDDEN_SNIPPETS:
        if forbidden.lower() in lowered:
            return False, "Script contains forbidden shell or dynamic execution."
    if _SPAWN_CALL_PATTERN.search(cleaned) is None:
        return False, "Script must contain at least one myrm_tools.spawn_subagent call."
    return True, None


def extract_template_placeholders(script_code: str) -> tuple[str, ...]:
    """Return unique `{placeholder}` keys in first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _PLACEHOLDER_PATTERN.finditer(script_code):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def apply_template_args(script_code: str, template_args: dict[str, str] | None) -> str:
    normalized = normalize_template_args(template_args)
    ok, error = validate_template_args(script_code, normalized)
    if not ok:
        raise ValueError(error or "Invalid workflow template arguments.")
    if not normalized:
        return script_code

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in normalized:
            return normalized[key]
        return match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, script_code)


def _is_spawn_subagent_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "spawn_subagent":
        return False
    return isinstance(func.value, ast.Name) and func.value.id == "myrm_tools"


def _spawn_call_has_readonly_true(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg != "readonly":
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
            return True
    return False


def _collect_spawn_subagent_calls(script_code: str) -> list[ast.Call] | None:
    try:
        tree = ast.parse(script_code)
    except SyntaxError:
        return None
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_spawn_subagent_call(node):
            calls.append(node)
    return calls


def script_all_spawns_readonly(script_code: str) -> bool:
    spawn_calls = _collect_spawn_subagent_calls(script_code)
    if not spawn_calls:
        return False
    return all(_spawn_call_has_readonly_true(call) for call in spawn_calls)


def can_skip_plan_confirm(
    *,
    script_code: str,
    trust_latch: bool,
    estimated_cost_usd: float | None,
    cost_skip_threshold_usd: float = 1.0,
) -> bool:
    if not trust_latch:
        return False
    if estimated_cost_usd is not None and estimated_cost_usd > cost_skip_threshold_usd:
        return False
    return script_all_spawns_readonly(script_code)
