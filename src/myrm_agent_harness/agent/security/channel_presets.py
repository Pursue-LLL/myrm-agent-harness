"""Channel security presets — per-channel default capabilities & permissions.

Each channel type (web_chat, IM, cron) has a preset that defines:
- Which tool categories (capabilities) are available
- Which permission rules override the user's config

[INPUT]
- .types::Capability, SecurityConfig, DEFAULT_CAPABILITIES, DEFAULT_RULESET
  (POS: Foundation layer of the security type hierarchy.)
- .engine::merge (POS: Layers 1-5 of the security architecture. Pure deterministic evaluation.)
- .config::parse_security_config (POS: Called at application startup and on config updates. Pure functions.)

[OUTPUT]
- ChannelType: web_chat / im / cron
- ChannelSecurityPreset: (capabilities, ruleset) pair
- CHANNEL_PRESETS: registry of presets per channel type
- resolve_channel_type(): channel name → ChannelType
- get_local_browser_relaxation(): rules relaxing browser restrictions for local mode
- build_channel_security_config(): channel + user config + declared_capabilities → SecurityConfig

[POS]
Decouples channel-specific security policy from the generic Permission Engine.
Channel preset rules sit at the highest priority layer (merged last),
ensuring channel restrictions cannot be bypassed by user configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique

from myrm_agent_harness.agent.security.config import parse_security_config
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
    PrivacyPolicy,
    SecurityConfig,
)


@unique
class ChannelType(StrEnum):
    """Channel types with distinct security postures."""

    WEB_CHAT = "web_chat"
    IM = "im"
    CRON = "cron"


@dataclass(frozen=True, slots=True)
class ChannelSecurityPreset:
    """Per-channel default security configuration.

    ``capabilities`` restricts which tool categories the channel can use.
    ``ruleset`` overrides default permission rules (merged on top of user config).
    """

    capabilities: CapabilitySet
    ruleset: PermissionRuleset


_IM_CAPABILITIES: CapabilitySet = frozenset(
    {
        Capability("*", "*"),
        Capability("!browser_*", "*"),
    }
)

_LOCAL_BROWSER_RELAXATION: PermissionRuleset = (
    # Internal-IP navigation: override DEFAULT_RULESET DENY → ALLOW for local users
    PermissionRule("browser_navigate", "127.0.0.1*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "localhost*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "0.0.0.0*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "10.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.16.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.17.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.18.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.19.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.20.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.21.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.22.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.23.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.24.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.25.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.26.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.27.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.28.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.29.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.30.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "172.31.*", PermissionAction.ALLOW),
    PermissionRule("browser_navigate", "192.168.*", PermissionAction.ALLOW),
    # Safe browser operations: local users own their machine
    PermissionRule("browser_fill", "*", PermissionAction.ALLOW),
    PermissionRule("browser_upload", "*", PermissionAction.ALLOW),
    PermissionRule("browser_download", "*", PermissionAction.ALLOW),
    PermissionRule("browser_session", "*", PermissionAction.ALLOW),
)

CHANNEL_PRESETS: dict[ChannelType, ChannelSecurityPreset] = {
    ChannelType.WEB_CHAT: ChannelSecurityPreset(capabilities=DEFAULT_CAPABILITIES, ruleset=()),
    ChannelType.IM: ChannelSecurityPreset(
        capabilities=_IM_CAPABILITIES,
        ruleset=(
            PermissionRule("shell_exec", "*", PermissionAction.DENY),
            PermissionRule("code_interpreter", "*", PermissionAction.ASK),
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
        ),
    ),
    ChannelType.CRON: ChannelSecurityPreset(
        capabilities=DEFAULT_CAPABILITIES,
        ruleset=(
            PermissionRule("shell_exec", "*", PermissionAction.ALLOW),
            PermissionRule("code_interpreter", "*", PermissionAction.ALLOW),
            PermissionRule("mcp_invoke", "*", PermissionAction.ALLOW),
        ),
    ),
}


def get_local_browser_relaxation() -> PermissionRuleset:
    """Rules that relax browser restrictions for local mode (desktop / CLI).

    Local users own their machine and local network, so internal-IP
    navigation, form fill, upload, download, and session management
    are allowed without approval.
    """
    return _LOCAL_BROWSER_RELAXATION


_WEB_CHAT_CHANNEL_NAMES: frozenset[str] = frozenset({"web_chat"})


def resolve_channel_type(channel_name: str) -> ChannelType:
    """Map a channel name to its ChannelType for security preset lookup.

    Default-safe: unknown channels are classified as IM (least privilege).
    Only explicitly listed web_chat and cron get elevated permissions.
    """
    if channel_name in _WEB_CHAT_CHANNEL_NAMES:
        return ChannelType.WEB_CHAT
    if channel_name == "cron":
        return ChannelType.CRON
    return ChannelType.IM


def build_channel_security_config(
    channel_name: str,
    user_config_raw: dict[str, object] | None = None,
    *,
    agent_security_raw: dict[str, object] | None = None,
    declared_capabilities: tuple[str, ...] = (),
    declared_allowed_roots: tuple[str, ...] = (),
    local_mode: bool = False,
    privacy_policy: PrivacyPolicy | None = None,
) -> SecurityConfig:
    """Build a SecurityConfig combining channel presets with user + agent overrides.

    Merge order (last-match-wins):
    1. DEFAULT_RULESET (base)
    2. User-defined rules (from UI SecurityPolicySection)
    3. Agent-level overrides (per-agent security policy)
    4. Channel preset rules (highest priority — channel restrictions cannot be bypassed)
    5. Local relaxation (if ``local_mode`` — relaxes browser restrictions for local users)

    Agent merge semantics:
    - capabilities: intersection (Agent can only restrict, not expand)
    - allowed_roots: union (Agent can grant additional paths)
    - forbidden_paths: always preserved (cannot be overridden)
    - ruleset: Agent rules merged on top (higher priority)
    - timeout: Agent overrides user (if configured)

    For Cron jobs, ``declared_capabilities`` defines the exact capability set.
    ``declared_allowed_roots`` provides additional path access grants (union-merged
    with existing allowed_roots). Applies to all channel types.
    """
    channel_type = resolve_channel_type(channel_name)
    preset = CHANNEL_PRESETS[channel_type]

    user_config = parse_security_config(user_config_raw)
    agent_config = parse_security_config(agent_security_raw)
    effective = _merge_user_and_agent(user_config, agent_config)

    if effective:
        capabilities = _merge_capabilities(preset.capabilities, effective.capabilities)
        ruleset = merge(effective.ruleset, preset.ruleset)
        timeout = effective.approval_timeout_seconds
        timeout_behavior = effective.approval_timeout_behavior
        path_policy = effective.path_policy
    else:
        capabilities = preset.capabilities
        ruleset = merge(DEFAULT_RULESET, preset.ruleset)
        timeout = 120
        timeout_behavior = "deny"
        path_policy = PathPolicy()

    if local_mode:
        ruleset = merge(ruleset, _LOCAL_BROWSER_RELAXATION)

    if channel_type == ChannelType.CRON:
        capabilities = _build_declared_capability_set(declared_capabilities)

    if declared_allowed_roots:
        merged_roots = tuple(sorted(set(path_policy.allowed_roots) | set(declared_allowed_roots)))
        path_policy = PathPolicy(
            forbidden_paths=path_policy.forbidden_paths,
            allowed_roots=merged_roots,
            workspace_label=path_policy.workspace_label,
        )

    network_allowlist: tuple[str, ...] = ()
    domain_hitl_enabled = False
    auto_mode_enabled = False
    auto_review_model: str | None = None
    auto_review_timeout: float = 3.0
    yolo_mode_enabled = False
    yolo_mode_enabled_at: float | None = None
    yolo_mode_timeout: int | None = None
    if effective:
        network_allowlist = effective.network_allowlist
        domain_hitl_enabled = effective.domain_hitl_enabled
        auto_mode_enabled = effective.auto_mode_enabled
        auto_review_model = effective.auto_review_model
        auto_review_timeout = effective.auto_review_timeout_seconds
        yolo_mode_enabled = effective.yolo_mode_enabled
        yolo_mode_enabled_at = effective.yolo_mode_enabled_at
        yolo_mode_timeout = effective.yolo_mode_timeout

    result = SecurityConfig(
        capabilities=capabilities,
        ruleset=ruleset,
        approval_timeout_seconds=timeout,
        approval_timeout_behavior=timeout_behavior,
        path_policy=path_policy,
        network_allowlist=network_allowlist,
        domain_hitl_enabled=domain_hitl_enabled,
        auto_mode_enabled=auto_mode_enabled,
        auto_review_model=auto_review_model,
        auto_review_timeout_seconds=auto_review_timeout,
        yolo_mode_enabled=yolo_mode_enabled,
        yolo_mode_enabled_at=yolo_mode_enabled_at,
        yolo_mode_timeout=yolo_mode_timeout,
    )
    if privacy_policy is not None:
        object.__setattr__(result, "privacy_policy", privacy_policy)
    return result


def _merge_user_and_agent(user: SecurityConfig | None, agent: SecurityConfig | None) -> SecurityConfig | None:
    """Merge user-level config with per-agent overrides.

    - capabilities: intersection (Agent restricts, never expands)
    - allowed_roots: union (Agent can grant additional paths)
    - forbidden_paths: always DEFAULT (cannot be overridden)
    - ruleset: Agent rules merged on top (higher priority via last-match-wins)
    - timeout: Agent overrides user if explicitly configured (non-default)
    """
    if agent is None:
        return user
    if user is None:
        return agent

    agent_positives = frozenset(c for c in agent.capabilities if not c.permission.startswith("!"))
    if agent_positives:
        user_positives = frozenset(c for c in user.capabilities if not c.permission.startswith("!"))
        all_negatives = frozenset(c for c in user.capabilities if c.permission.startswith("!")) | frozenset(
            c for c in agent.capabilities if c.permission.startswith("!")
        )
        caps = (user_positives & agent_positives) | all_negatives
    else:
        caps = user.capabilities

    ruleset = merge(user.ruleset, agent.ruleset)

    allowed = tuple(sorted(set(user.path_policy.allowed_roots) | set(agent.path_policy.allowed_roots)))
    label = agent.path_policy.workspace_label or user.path_policy.workspace_label
    pp = PathPolicy(forbidden_paths=user.path_policy.forbidden_paths, allowed_roots=allowed, workspace_label=label)

    timeout = agent.approval_timeout_seconds if agent.approval_timeout_seconds != 120 else user.approval_timeout_seconds
    timeout_behavior = (
        agent.approval_timeout_behavior if agent.approval_timeout_behavior != "deny" else user.approval_timeout_behavior
    )

    network_allowlist = tuple(sorted(set(user.network_allowlist) | set(agent.network_allowlist)))
    domain_hitl_enabled = user.domain_hitl_enabled or agent.domain_hitl_enabled
    auto_mode_enabled = user.auto_mode_enabled or agent.auto_mode_enabled
    auto_review_model = agent.auto_review_model or user.auto_review_model
    auto_review_timeout = min(user.auto_review_timeout_seconds, agent.auto_review_timeout_seconds)

    yolo_enabled = user.yolo_mode_enabled or agent.yolo_mode_enabled
    yolo_at = user.yolo_mode_enabled_at or agent.yolo_mode_enabled_at
    yolo_timeout = user.yolo_mode_timeout if user.yolo_mode_enabled else agent.yolo_mode_timeout

    return SecurityConfig(
        capabilities=caps,
        ruleset=ruleset,
        approval_timeout_seconds=timeout,
        approval_timeout_behavior=timeout_behavior,
        path_policy=pp,
        network_allowlist=network_allowlist,
        domain_hitl_enabled=domain_hitl_enabled,
        auto_mode_enabled=auto_mode_enabled,
        auto_review_model=auto_review_model,
        auto_review_timeout_seconds=auto_review_timeout,
        yolo_mode_enabled=yolo_enabled,
        yolo_mode_enabled_at=yolo_at,
        yolo_mode_timeout=yolo_timeout,
    )


def _merge_capabilities(preset: CapabilitySet, user: CapabilitySet) -> CapabilitySet:
    """Merge channel preset capabilities with user-defined capabilities.

    Negative capabilities (``!`` prefix) from the preset are always preserved
    — they represent hard channel constraints that users cannot bypass.
    Positive capabilities are intersected when the preset is restrictive
    (not DEFAULT_CAPABILITIES), or taken from user config when the preset
    is permissive.
    """
    preset_negatives = frozenset(c for c in preset if c.permission.startswith("!"))
    preset_positives = preset - preset_negatives

    if preset_positives == DEFAULT_CAPABILITIES:
        return user | preset_negatives

    return (preset_positives & user) | preset_negatives


def _build_declared_capability_set(names: tuple[str, ...]) -> CapabilitySet:
    """Convert a list of capability names to a CapabilitySet.

    Each name becomes a Capability(name, "*") grant.
    """
    return frozenset(Capability(name, "*") for name in names)
