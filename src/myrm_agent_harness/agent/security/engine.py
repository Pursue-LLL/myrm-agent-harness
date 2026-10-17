"""Permission Engine — wildcard-based rule evaluation for tool-level access control.

[INPUT]
  PermissionRuleset, SecurityConfig, DEFAULT_CAPABILITIES

[OUTPUT]
- evaluate(): resolve action for a (permission, target) pair via last-match-wins
- evaluate_tool_call(): deterministic evaluation (Layers 1–5)
  (capability → shell_command_analyzer → command_denylist → URL scheme check
   → domain HITL → path_policy → target-aware ruleset → risk_classifier fallback).
  A command-bearing tool is judged command by command (see command_rules.py) when a
  pattern rule could tell the commands of the line apart.
- check_tool_path_policy(): path-zone verdict for a file tool's ``path`` (engine and cron policy share it)
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

from myrm_agent_harness.agent.security.command_rules import (
    COMMAND_BEARING_PERMISSIONS,
    check_command_denylist,
    command_text,
    judge_command,
)
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


def _check_domain_blocklist(
    permission: str, tool_input: dict[str, object], network_blocklist: tuple[str, ...]
) -> tuple[PermissionAction | None, str]:
    """Deny URL-bearing tools when hostname matches network blocklist."""
    if permission not in _URL_BEARING_PERMISSIONS or not network_blocklist:
        return None, ""
    url = str(tool_input.get("url", "")).strip()
    if not url:
        return None, ""
    hostname = _extract_url_host(url)
    if not hostname:
        return None, ""
    if _domain_in_allowlist(hostname, network_blocklist):
        return PermissionAction.DENY, f"Domain '{hostname}' is blocked by policy"
    return None, ""


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


def _resolve_target(permission: str, tool_input: dict[str, object], *, tool_name: str | None = None) -> str:
    """Extract the target resource from tool_input for pattern matching.

    For URL-bearing permissions (``browser_navigate``, ``web_fetch``),
    extracts the hostname so that rules like ``192.168.*`` or ``*.example.com``
    match regardless of scheme or path.
    For ``mcp_invoke``, uses the full tool name (e.g. ``mcp__gmail__send_email``)
    as the target, enabling per-tool rules like
    ``{"mcp_invoke": {"mcp__gmail__send_email": "ask", "*": "allow"}}``.
    For ``shell_exec`` and ``code_interpreter`` (the bash tool), uses the command text.
    For other permissions, returns the raw field value.
    Returns ``"*"`` when no target extraction is needed.
    """
    if permission == "mcp_invoke" and tool_name:
        return tool_name
    if permission in COMMAND_BEARING_PERMISSIONS:
        return command_text(tool_input) or "*"
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


def _governing_rule(permission: str, target: str, ruleset: PermissionRuleset, tool_name: str | None) -> PermissionRule:
    """The rule that decides *target*: the last matching rule of the tool's own name, else the last for the permission."""
    if tool_name and tool_name != permission:
        specific: PermissionRule | None = None
        for rule in ruleset:
            if (
                rule.permission != "*"
                and _wildcard_match(tool_name, rule.permission)
                and _wildcard_match(target, rule.pattern)
            ):
                specific = rule
        if specific is not None:
            return specific
    return evaluate(permission, target, ruleset)


def _has_pattern_rules(ruleset: PermissionRuleset, permission: str, tool_name: str | None) -> bool:
    """Whether a rule other than a blanket ``*`` could govern this call, so that the target text matters."""
    names = (permission, tool_name) if tool_name else (permission,)
    return any(
        rule.pattern != "*" and any(_wildcard_match(name, rule.permission) for name in names) for rule in ruleset
    )


def _rule_decision(
    permission: str, target: str, ruleset: PermissionRuleset, tool_name: str | None
) -> tuple[PermissionAction, bool]:
    """The ruleset's action for a call, and whether the read-only classifier may still turn an ASK into an ALLOW.

    Shell tools are judged command by command, but only when a pattern rule could tell commands apart: with
    blanket rules alone the command text cannot change the outcome, so the line is not even split.
    """

    def resolve(text: str) -> PermissionRule:
        return _governing_rule(permission, text, ruleset, tool_name)

    if permission in COMMAND_BEARING_PERMISSIONS and _has_pattern_rules(ruleset, permission, tool_name):
        return judge_command(target, resolve)
    return resolve(target).action, True


def check_tool_path_policy(
    permission: str,
    tool_input: dict[str, object],
    config: SecurityConfig,
    workspace_root: str | None,
) -> tuple[PermissionAction, str] | None:
    """Path-zone verdict (session grants included) for a file tool's ``path``; ``None`` if there is none to check."""
    raw_path = str(tool_input.get("path", ""))
    if permission not in _PATH_CHECKED_PERMISSIONS or not raw_path:
        return None

    from myrm_agent_harness.agent.security.checks import check_path_policy
    from myrm_agent_harness.agent.security.session_access import merge_path_policy_with_session_access

    return check_path_policy(
        raw_path,
        merge_path_policy_with_session_access(config.path_policy),
        workspace_root,
        require_write=permission == "file_write",
    )


def evaluate_tool_call(
    permission: str,
    tool_input: dict[str, object],
    config: SecurityConfig,
    *,
    workspace_root: str | None = None,
    tool_name: str | None = None,
) -> tuple[PermissionAction, str]:
    """Top-level entry point: evaluate a tool call against the full security config.

    ``permission`` is the abstract permission type (e.g. ``shell_exec``),
    not the concrete LangChain tool name. Callers must resolve the tool name
    to a permission type via ``tool_registry.resolve_permission_type()``
    before calling this function.

    ``tool_name`` is the original LangChain tool name, passed through for
    target resolution. For ``mcp_invoke`` permission, the tool name
    (e.g. ``mcp__gmail__send_email``) is used as the pattern-matching target,
    enabling per-MCP-tool rules in the permission ruleset.

    Evaluation order:
    1. Capability Fence → not granted → DENY
    2a. Shell Command Analyzer → BLOCK → DENY, ESCALATE → ASK
    2a.5. Command Denylist → user-defined fnmatch globs → DENY (YOLO-proof)
    2b. URL Scheme Check → non-http(s) → DENY
    2c. Domain HITL → domain not in allowlist → ASK (when enabled)
    3. Path Policy → forbidden/allowed/workspace check (file_read/file_write only)
    4. Permission ruleset with target resolution → last-match-wins
    5. Risk classifier fallback → SAFE shell commands → ALLOW (shell_exec/code_interpreter)
    6. Fallback → ASK

    Returns (action, reason). Reason is empty for ALLOW.
    """
    from myrm_agent_harness.agent.security.checks import (
        check_navigate_scheme,
        check_shell_threats,
    )

    if not check_capability(permission, "*", config.capabilities):
        return PermissionAction.DENY, f"Capability not granted: {permission}"

    threat_action, threat_reason = check_shell_threats(permission, tool_input)
    if threat_action is not None:
        return threat_action, threat_reason

    deny_action, deny_reason = check_command_denylist(permission, tool_input, config.command_denylist)
    if deny_action is not None:
        return deny_action, deny_reason

    scheme_action, scheme_reason = check_navigate_scheme(permission, tool_input)
    if scheme_action is not None:
        return scheme_action, scheme_reason

    block_action, block_reason = _check_domain_blocklist(permission, tool_input, config.network_blocklist)
    if block_action is not None:
        return block_action, block_reason

    target = _resolve_target(permission, tool_input, tool_name=tool_name)
    result_action, classifier_may_allow = _rule_decision(permission, target, config.ruleset, tool_name)

    # Hardline rule: An explicit DENY from user/policy ruleset must never be weakened to ASK
    if result_action == PermissionAction.DENY:
        return PermissionAction.DENY, f"Permission '{tool_name or permission}' denied by policy"

    if config.domain_hitl_enabled:
        domain_action, domain_reason = _check_domain_policy(permission, tool_input, config.network_allowlist)
        if domain_action is not None:
            return domain_action, domain_reason

    path_verdict = check_tool_path_policy(permission, tool_input, config, workspace_root)
    if path_verdict is not None and path_verdict[0] in (PermissionAction.DENY, PermissionAction.ASK):
        return path_verdict

    if result_action == PermissionAction.ASK and classifier_may_allow and permission in COMMAND_BEARING_PERMISSIONS:
        from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
            CommandRiskLevel,
            classify_command_risk,
        )

        command = command_text(tool_input)
        if command and classify_command_risk(command) == CommandRiskLevel.SAFE:
            reason = (
                "Sandbox-aware safe command auto-allow"
                if getattr(config, "is_sandbox", False)
                else "Safe read-only command auto-allow"
            )
            return PermissionAction.ALLOW, reason

    return result_action, ""


def merge(*rulesets: PermissionRuleset) -> PermissionRuleset:
    """Combine multiple rulesets in order (earlier = lower priority)."""
    combined: list[PermissionRule] = []
    for ruleset in rulesets:
        combined.extend(ruleset)
    return tuple(combined)


def disabled_permissions(
    permissions: list[str],
    ruleset: PermissionRuleset,
    capabilities: CapabilitySet = DEFAULT_CAPABILITIES,
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
