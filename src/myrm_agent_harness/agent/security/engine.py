"""Permission Engine — wildcard-based rule evaluation for tool-level access control.

[INPUT]
  PermissionRuleset, SecurityConfig, DEFAULT_CAPABILITIES

[OUTPUT]
- evaluate(): resolve action for a (permission, target) pair via last-match-wins
- evaluate_tool_call(): deterministic evaluation (Layers 1–5)
  (capability → shell_command_analyzer → URL scheme check → domain HITL
   → path_policy → target-aware ruleset → risk_classifier fallback).
- check_capability(): test (permission, target) against a CapabilitySet
- merge(): combine multiple rulesets
- disabled_permissions(): find unconditionally denied permission types
- extract_url_domains(): extract hostnames from URL-bearing tool arguments

[POS]
Layers 1–5 of the security architecture. Pure deterministic evaluation —
no side effects, no I/O, trivially testable.
Layer 4.5 (LLM security review) is handled separately in batch_processor.py
since it requires async I/O; this keeps the engine pure.
"""

from __future__ import annotations

from fnmatch import fnmatch
from urllib.parse import urlparse

from myrm_agent_harness.agent.security.types import (
    DEFAULT_CAPABILITIES,
    CapabilitySet,
    PermissionAction,
    PermissionRule,
    PermissionRuleset,
    SecurityConfig,
)


def _wildcard_match(value: str, pattern: str) -> bool:
    """Match a value against a pattern using fnmatch semantics."""
    if pattern == "*":
        return True
    return fnmatch(value, pattern)


def evaluate(permission: str, target: str, *rulesets: PermissionRuleset) -> PermissionRule:
    """Resolve the effective rule for a (permission, target) pair.

    Uses **last-match-wins** semantics: later rulesets override earlier ones,
    and within a ruleset, later rules override earlier ones. This allows
    user-defined rules to precisely override any default.

    Returns the matching rule, or a fallback ``ASK`` rule if nothing matches.
    """
    merged = merge(*rulesets)
    match: PermissionRule | None = None
    for rule in merged:
        if _wildcard_match(permission, rule.permission) and _wildcard_match(target, rule.pattern):
            match = rule
    return match or PermissionRule(permission, "*", PermissionAction.ASK)


def check_capability(permission: str, target: str, capabilities: CapabilitySet) -> bool:
    """Check if (permission, target) is within the granted capability set.

    Negative capabilities (``!`` prefix) are evaluated first and take
    precedence: if any negative capability matches, the check fails
    immediately regardless of positive grants.
    """
    for cap in capabilities:
        if (
            cap.permission.startswith("!")
            and _wildcard_match(permission, cap.permission[1:])
            and _wildcard_match(target, cap.pattern)
        ):
            return False
    return any(
        not cap.permission.startswith("!")
        and _wildcard_match(permission, cap.permission)
        and _wildcard_match(target, cap.pattern)
        for cap in capabilities
    )


_TARGET_EXTRACTORS: dict[str, str] = {
    "browser_navigate": "url",
    "web_fetch": "url",
    "net_fetch": "url",
    "shell_exec": "command",
    "file_read": "path",
    "file_write": "path",
}

_URL_BEARING_PERMISSIONS: frozenset[str] = frozenset({"web_fetch", "net_fetch", "browser_navigate"})
_PATH_CHECKED_PERMISSIONS: frozenset[str] = frozenset({"file_read", "file_write"})


def _domain_in_allowlist(hostname: str, allowlist: tuple[str, ...]) -> bool:
    """Check if *hostname* matches any entry in *allowlist*.

    Supports exact match and suffix match (entries starting with ``"."``).
    """
    lower = hostname.lower()
    for entry in allowlist:
        if entry.startswith("."):
            if lower == entry[1:] or lower.endswith(entry):
                return True
        elif lower == entry:
            return True
    return False


def _extract_url_host(url: str) -> str:
    """Extract the hostname from a URL for pattern matching.

    Handles both scheme-prefixed URLs (``http://192.168.1.1/path``)
    and bare host:port (``localhost:3000``).
    """
    if "://" in url:
        parsed = urlparse(url)
        return parsed.hostname or url
    host = url.split(":")[0].split("/")[0]
    return host or url


def _check_domain_policy(
    permission: str, tool_input: dict[str, object], network_allowlist: tuple[str, ...]
) -> tuple[PermissionAction | None, str]:
    """Check URL-bearing tools against the network domain allowlist (Layer 2c).

    Only applies when ``domain_hitl_enabled`` is True. Returns ASK for URLs
    whose hostname is not in the allowlist. Callers gate on ``domain_hitl_enabled``.
    """
    if permission not in _URL_BEARING_PERMISSIONS:
        return None, ""
    url = str(tool_input.get("url", "")).strip()
    if not url:
        return None, ""
    hostname = _extract_url_host(url)
    if not hostname:
        return None, ""
    if _domain_in_allowlist(hostname, network_allowlist):
        return None, ""
    return PermissionAction.ASK, f"Domain '{hostname}' requires approval"


def _resolve_target(permission: str, tool_input: dict[str, object]) -> str:
    """Extract the target resource from tool_input for pattern matching.

    For URL-bearing permissions (``browser_navigate``, ``web_fetch``),
    extracts the hostname so that rules like ``192.168.*`` or ``*.example.com``
    match regardless of scheme or path.
    For other permissions, returns the raw field value.
    Returns ``"*"`` when no target extraction is needed.
    """
    key = _TARGET_EXTRACTORS.get(permission)
    if not key:
        return "*"
    value = tool_input.get(key)
    if not value:
        return "*"
    raw = str(value)
    if permission in _URL_BEARING_PERMISSIONS:
        return _extract_url_host(raw)
    return raw


def evaluate_tool_call(
    permission: str, tool_input: dict[str, object], config: SecurityConfig, *, workspace_root: str | None = None
) -> tuple[PermissionAction, str]:
    """Top-level entry point: evaluate a tool call against the full security config.

    ``permission`` is the abstract permission type (e.g. ``shell_exec``),
    not the concrete LangChain tool name. Callers must resolve the tool name
    to a permission type via ``tool_registry.resolve_permission_type()``
    before calling this function.

    Evaluation order:
    1. Capability Fence → not granted → DENY
    2a. Shell Command Analyzer → BLOCK → DENY, ESCALATE → ASK
    2b. URL Scheme Check → non-http(s) → DENY
    2c. Domain HITL → domain not in allowlist → ASK (when enabled)
    3. Path Policy → forbidden/allowed/workspace check (file_read/file_write only)
    4. Permission ruleset with target resolution → last-match-wins
    5. Risk classifier fallback → SAFE shell commands → ALLOW (shell_exec/code_interpreter)
    6. Fallback → ASK

    Returns (action, reason). Reason is empty for ALLOW.
    """
    from myrm_agent_harness.agent.security.checks import check_navigate_scheme, check_path_policy, check_shell_threats

    if not check_capability(permission, "*", config.capabilities):
        return PermissionAction.DENY, f"Capability not granted: {permission}"

    threat_action, threat_reason = check_shell_threats(permission, tool_input)
    if threat_action is not None:
        return threat_action, threat_reason

    scheme_action, scheme_reason = check_navigate_scheme(permission, tool_input)
    if scheme_action is not None:
        return scheme_action, scheme_reason

    if config.domain_hitl_enabled:
        domain_action, domain_reason = _check_domain_policy(permission, tool_input, config.network_allowlist)
        if domain_action is not None:
            return domain_action, domain_reason

    if permission in _PATH_CHECKED_PERMISSIONS:
        raw_path = str(tool_input.get("path", ""))
        if raw_path:
            path_action, path_reason = check_path_policy(raw_path, config.path_policy, workspace_root)
            if path_action in (PermissionAction.DENY, PermissionAction.ASK):
                return path_action, path_reason

    target = _resolve_target(permission, tool_input)
    result = evaluate(permission, target, config.ruleset)

    if result.action == PermissionAction.ASK and permission in ("shell_exec", "code_interpreter"):
        from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
            CommandRiskLevel,
            classify_command_risk,
        )

        command = str(tool_input.get("command", "")).strip()
        if command and classify_command_risk(command) == CommandRiskLevel.SAFE:
            return PermissionAction.ALLOW, ""

    return result.action, ""


def merge(*rulesets: PermissionRuleset) -> PermissionRuleset:
    """Combine multiple rulesets in order (earlier = lower priority)."""
    combined: list[PermissionRule] = []
    for ruleset in rulesets:
        combined.extend(ruleset)
    return tuple(combined)


def disabled_permissions(
    permissions: list[str], ruleset: PermissionRuleset, capabilities: CapabilitySet = DEFAULT_CAPABILITIES
) -> frozenset[str]:
    """Return permission types that are unconditionally denied.

    A permission is disabled if:
    - It fails the capability fence (not granted or negatively excluded), OR
    - Its ruleset evaluation yields DENY with pattern ``"*"``

    Useful for stripping denied tools from the LLM tool list before invocation.
    Callers should pass permission types (e.g. ``shell_exec``), not tool names.
    """
    result: set[str] = set()
    for perm in permissions:
        if not check_capability(perm, "*", capabilities):
            result.add(perm)
            continue
        rule = evaluate(perm, "*", ruleset)
        if rule.action == PermissionAction.DENY:
            result.add(perm)
    return frozenset(result)


def extract_url_domains(permission: str, tool_input: dict[str, object]) -> tuple[str, ...]:
    """Extract hostnames from URL-bearing tool arguments.

    Returns a tuple of lowercased hostnames found in the tool's URL parameters.
    Empty tuple if the permission type has no URL parameters or none are present.
    """
    if permission not in _URL_BEARING_PERMISSIONS:
        return ()
    url = str(tool_input.get("url", "")).strip()
    if not url:
        return ()
    hostname = _extract_url_host(url)
    if hostname:
        return (hostname.lower(),)
    return ()
