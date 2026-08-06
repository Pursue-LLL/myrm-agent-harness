"""Validation helpers for persisted Dynamic Workflow orchestration scripts.

[INPUT]
- None (pure validation utilities)

[OUTPUT]
- validate_orchestration_script, apply_template_args, can_skip_plan_confirm

[POS]
Trust and safety guardrails for named workflow template save and pinned rerun paths.
"""

from __future__ import annotations

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
_READONLY_SPAWN_PATTERN = re.compile(
    r"myrm_tools\.spawn_subagent\s*\([^)]*readonly\s*=\s*True",
    re.DOTALL,
)
_PLACEHOLDER_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


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


def apply_template_args(script_code: str, template_args: dict[str, str]) -> str:
    if not template_args:
        return script_code

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in template_args:
            return str(template_args[key])
        return match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, script_code)


def script_all_spawns_readonly(script_code: str) -> bool:
    spawn_count = len(_SPAWN_CALL_PATTERN.findall(script_code))
    if spawn_count == 0:
        return False
    readonly_count = len(_READONLY_SPAWN_PATTERN.findall(script_code))
    return readonly_count >= spawn_count


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
