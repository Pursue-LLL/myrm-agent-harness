"""Tool safety registry domain — built-in tool names, safety metadata, PTC registration.

Aggregates ``registry.py`` (tool registry SSOT: built-in tool names, safety
metadata, permission resolution, PTC registration) and ``safety.py`` (module-load
gate warning on missing safety declarations) behind ``core.security.tool_registry``,
preserving the flat-module import surface for all consumers.

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- BUILTIN_TOOL_NAMES / TOOL_SAFETY_METADATA — tool safety SSOT
- TOOL_PERMISSION_MAP / AUTO_APPROVED_BUILTIN_TOOLS / EXPLICIT_MCP_FALLBACK_TOOLS / DYNAMICALLY_RESOLVED_TOOL_NAMES / RULESET_COVERAGE_WHITELIST — governance audit declarations
- SafetyMetadata / MCPAnnotations / resolve_safety_metadata / resolve_permission_type
- register_ptc_safety_metadata / get_ptc_safety_metadata / compute_canonical_args_hash
- check_safety_coverage / _check_safety_coverage — module-load safety gate
- _sanitize_url_for_taint / _FAIL_CLOSED_DEFAULTS / _PTC_* — internal helpers
"""

from .registry import (
    _FAIL_CLOSED_DEFAULTS,
    _PTC_SAFETY_METADATA,
    _PTC_TOOL_FLAT_INDEX,
    AUTO_APPROVE_REASONS,
    AUTO_APPROVED_BUILTIN_TOOLS,
    BUILTIN_TOOL_NAMES,
    DYNAMICALLY_RESOLVED_TOOL_NAMES,
    EXPLICIT_MCP_FALLBACK_TOOLS,
    RULESET_COVERAGE_WHITELIST,
    TOOL_CANONICAL_PARAMS,
    TOOL_GROUP_MAP,
    TOOL_GROUP_NAMES,
    TOOL_PERMISSION_MAP,
    TOOL_SAFETY_METADATA,
    TOOL_TO_GROUP,
    MCPAnnotations,
    SafetyMetadata,
    _check_safety_coverage,
    _sanitize_url_for_taint,
    compute_canonical_args_hash,
    get_ptc_safety_metadata,
    register_ptc_safety_metadata,
    resolve_permission_type,
    resolve_safety_metadata,
    unregister_ptc_safety_metadata,
    evict_skill_safety_metadata,
)
from .safety import check_safety_coverage

__all__ = [
    "AUTO_APPROVED_BUILTIN_TOOLS",
    "AUTO_APPROVE_REASONS",
    "BUILTIN_TOOL_NAMES",
    "DYNAMICALLY_RESOLVED_TOOL_NAMES",
    "EXPLICIT_MCP_FALLBACK_TOOLS",
    "RULESET_COVERAGE_WHITELIST",
    "TOOL_CANONICAL_PARAMS",
    "TOOL_GROUP_MAP",
    "TOOL_GROUP_NAMES",
    "TOOL_PERMISSION_MAP",
    "TOOL_SAFETY_METADATA",
    "TOOL_TO_GROUP",
    "_FAIL_CLOSED_DEFAULTS",
    "_PTC_SAFETY_METADATA",
    "_PTC_TOOL_FLAT_INDEX",
    "MCPAnnotations",
    "SafetyMetadata",
    "_check_safety_coverage",
    "_sanitize_url_for_taint",
    "check_safety_coverage",
    "compute_canonical_args_hash",
    "get_ptc_safety_metadata",
    "register_ptc_safety_metadata",
    "resolve_permission_type",
    "resolve_safety_metadata",
    "unregister_ptc_safety_metadata",
    "evict_skill_safety_metadata",
]
