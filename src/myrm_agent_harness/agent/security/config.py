"""Security config parsing — deserialise JSON config into SecurityConfig.

Converts raw JSON/dict configuration into typed SecurityConfig, PermissionRuleset,
CapabilitySet, and PathPolicy objects.

[INPUT]
  PermissionRuleset, SecurityConfig, DEFAULT_CAPABILITIES, DEFAULT_RULESET

[OUTPUT]
- from_config(): deserialise permission rules from config dict
- parse_security_config(): full SecurityConfig from JSON

[POS]
Called at application startup and on config updates. Pure functions.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.engine import merge
from myrm_agent_harness.agent.security.types import (
    DEFAULT_CAPABILITIES,
    DEFAULT_RULESET,
    Capability,
    CapabilitySet,
    PathPolicy,
    PermissionAction,
    PermissionRule,
    PermissionRuleset,
    SecurityConfig,
    _default_dangerous_paths,
)
from myrm_agent_harness.utils.coercion import parse_float, parse_int


def from_config(raw: dict[str, str | dict[str, str]]) -> PermissionRuleset:
    """Deserialise a config dict into a PermissionRuleset.

    Accepts two formats::

        # Simple: permission → action
        {"shell_exec": "ask", "file_write": "deny"}

        # Nested: permission → {pattern: action}
        {"file_read": {"*": "allow", "*.env": "ask"}}

    Returns a PermissionRuleset (tuple of PermissionRule).
    """
    rules: list[PermissionRule] = []
    for key, value in raw.items():
        if isinstance(value, str):
            rules.append(PermissionRule(permission=key, pattern="*", action=PermissionAction(value)))
        elif isinstance(value, dict):
            for pattern, action in value.items():
                rules.append(PermissionRule(permission=key, pattern=pattern, action=PermissionAction(str(action))))
    return tuple(rules)


def _parse_capabilities(raw: list[dict[str, str] | str]) -> CapabilitySet:
    """Parse a list of capability grants into a CapabilitySet.

    Accepts two formats per entry::

        "shell_exec"                         → Capability("shell_exec", "*")
        {"permission": "file_read", "pattern": "*.py"} → Capability("file_read", "*.py")
    """
    caps: set[Capability] = set()
    for entry in raw:
        if isinstance(entry, str):
            caps.add(Capability(entry, "*"))
        elif isinstance(entry, dict):
            caps.add(Capability(permission=str(entry.get("permission", "*")), pattern=str(entry.get("pattern", "*"))))
    return frozenset(caps)


def _parse_path_policy(raw: dict[str, object]) -> PathPolicy:
    """Parse a pathPolicy config dict into a PathPolicy.

    Expected format::

        {
            "forbiddenPaths": ["~/.ssh", "/etc/shadow"],
            "allowedRoots": ["~/.claude", "~/projects"],
            "workspaceLabel": "My Projects"
        }

    Missing fields use defaults.
    """
    forbidden = _default_dangerous_paths()
    forbidden_raw = raw.get("forbiddenPaths")
    if isinstance(forbidden_raw, list):
        forbidden = frozenset(str(p) for p in forbidden_raw) | _default_dangerous_paths()

    allowed: tuple[str, ...] = ()
    allowed_raw = raw.get("allowedRoots")
    if isinstance(allowed_raw, list):
        allowed = tuple(str(p) for p in allowed_raw)

    workspace_label_raw = raw.get("workspaceLabel")
    workspace_label = str(workspace_label_raw) if workspace_label_raw else None

    return PathPolicy(forbidden_paths=forbidden, allowed_roots=allowed, workspace_label=workspace_label)


def parse_security_config(raw: dict[str, object] | None) -> SecurityConfig | None:
    """Parse a JSON config dict into a SecurityConfig.

    Expected format::

        {
            "capabilities": [
                "shell_exec",
                {"permission": "file_read", "pattern": "*.py"}
            ],
            "permissions": {"shell_exec": "ask", "file_read": {"*.env": "ask"}},
            "approvalTimeoutSeconds": 120,
            "approvalTimeoutBehavior": "deny",
            "pathPolicy": {
                "forbiddenPaths": ["~/.ssh"],
                "allowedRoots": ["~/.claude"]
            }
        }

    Returns None if *raw* is None or empty — meaning "no config, use defaults".
    """
    if not raw:
        return None

    timeout_raw = raw.get("approvalTimeoutSeconds", 120)
    timeout = parse_int(timeout_raw, 120, min_val=1, max_val=3600)

    timeout_behavior_raw = raw.get("approvalTimeoutBehavior", "deny")
    timeout_behavior = str(timeout_behavior_raw) if timeout_behavior_raw in ("deny", "allow") else "deny"

    capabilities: CapabilitySet = DEFAULT_CAPABILITIES
    capabilities_raw = raw.get("capabilities")
    if isinstance(capabilities_raw, list):
        capabilities = _parse_capabilities(capabilities_raw)

    ruleset: PermissionRuleset = DEFAULT_RULESET
    permissions_raw = raw.get("permissions")
    if isinstance(permissions_raw, dict):
        user_ruleset = from_config(permissions_raw)
        ruleset = merge(DEFAULT_RULESET, user_ruleset)

    path_policy = PathPolicy()
    path_policy_raw = raw.get("pathPolicy")
    if isinstance(path_policy_raw, dict):
        path_policy = _parse_path_policy(path_policy_raw)

    network_allowlist: tuple[str, ...] = ()
    allowlist_raw = raw.get("networkAllowlist")
    if isinstance(allowlist_raw, list):
        network_allowlist = tuple(s.strip().lower() for s in allowlist_raw if isinstance(s, str) and s.strip())

    network_blocklist: tuple[str, ...] = ()
    blocklist_raw = raw.get("networkBlocklist")
    if isinstance(blocklist_raw, list):
        network_blocklist = tuple(s.strip().lower() for s in blocklist_raw if isinstance(s, str) and s.strip())

    domain_hitl_enabled = bool(raw.get("domainHitlEnabled", True))

    auto_review_enabled = bool(raw.get("autoModeEnabled") or raw.get("autoReviewEnabled", False))
    auto_review_model_raw = raw.get("autoReviewModel")
    auto_review_model = str(auto_review_model_raw) if auto_review_model_raw else None
    auto_review_timeout_raw = raw.get("autoReviewTimeoutSeconds", 3.0)
    auto_review_timeout = parse_float(auto_review_timeout_raw, 3.0, min_val=0.1, max_val=60.0)

    transcript_window_raw = raw.get("transcriptWindowSize", 20)
    transcript_window_size = parse_int(transcript_window_raw, 20, min_val=1, max_val=200)

    plan_confirm_enabled = bool(raw.get("planConfirmEnabled") or raw.get("plan_confirm_enabled", False))

    yolo_mode_enabled = bool(raw.get("yoloModeEnabled") or raw.get("yolo_mode_enabled", False))
    yolo_mode_enabled_at_raw = raw.get("yolo_mode_enabled_at")
    yolo_mode_enabled_at = parse_float(yolo_mode_enabled_at_raw, 0.0) if yolo_mode_enabled_at_raw is not None else None
    yolo_mode_timeout_raw = raw.get("yolo_mode_timeout")
    yolo_mode_timeout = parse_int(yolo_mode_timeout_raw, 0, min_val=1) if yolo_mode_timeout_raw is not None else None

    return SecurityConfig(
        capabilities=capabilities,
        ruleset=ruleset,
        approval_timeout_seconds=timeout,
        approval_timeout_behavior=timeout_behavior,
        path_policy=path_policy,
        network_allowlist=network_allowlist,
        network_blocklist=network_blocklist,
        domain_hitl_enabled=domain_hitl_enabled,
        auto_mode_enabled=auto_review_enabled,
        auto_review_model=auto_review_model,
        auto_review_timeout_seconds=auto_review_timeout,
        transcript_window_size=transcript_window_size,
        plan_confirm_enabled=plan_confirm_enabled,
        yolo_mode_enabled=yolo_mode_enabled,
        yolo_mode_enabled_at=yolo_mode_enabled_at,
        yolo_mode_timeout=yolo_mode_timeout,
    )


def _ruleset_to_permissions(ruleset: PermissionRuleset) -> dict[str, str]:
    permissions: dict[str, str] = {}
    for rule in ruleset:
        if rule.pattern == "*":
            permissions[rule.permission] = rule.action.value
    return permissions


def apply_remote_exposed_overlay(base: SecurityConfig) -> SecurityConfig:
    """Merge remote-exposed deny rules onto an existing session SecurityConfig."""
    remote = SecurityConfig.remote_exposed()
    return SecurityConfig(
        capabilities=base.capabilities,
        ruleset=merge(base.ruleset, remote.ruleset),
        approval_timeout_seconds=base.approval_timeout_seconds,
        approval_timeout_behavior=base.approval_timeout_behavior,
        path_policy=base.path_policy,
        network_allowlist=base.network_allowlist,
        network_blocklist=base.network_blocklist,
        domain_hitl_enabled=base.domain_hitl_enabled,
        privacy_policy=base.privacy_policy,
        auto_mode_enabled=base.auto_mode_enabled,
        auto_review_model=base.auto_review_model,
        auto_review_timeout_seconds=base.auto_review_timeout_seconds,
        transcript_window_size=base.transcript_window_size,
        yolo_mode_enabled=False,
        yolo_mode_enabled_at=None,
        yolo_mode_timeout=None,
    )


def remote_exposed_permissions() -> dict[str, str]:
    """Deny-only permission keys for remote-exposed HTTP admission."""
    return _ruleset_to_permissions(SecurityConfig.remote_exposed().ruleset)


def security_config_to_dict(config: SecurityConfig) -> dict[str, object]:
    """Serialize SecurityConfig fields consumed by agent-server security_config_raw."""
    return {
        "permissions": _ruleset_to_permissions(config.ruleset),
        "yoloModeEnabled": config.yolo_mode_enabled,
        "yolo_mode_enabled": config.yolo_mode_enabled,
    }
