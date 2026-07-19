"""Security type definitions — shared data structures for the security subsystem.

Zero-dependency module providing all core types used across the security
subsystem. No internal imports — eliminates circular dependency by serving
as the single foundation layer.

[INPUT]
- (none — pure types, zero dependencies)

[OUTPUT]
- Capability / CapabilitySet / DEFAULT_CAPABILITIES: Layer 1 capability grants
- PermissionAction: allow / ask / deny
- PermissionRule / PermissionRuleset / DEFAULT_RULESET: Layer 3 rules
- PathPolicy: Layer 2.5 path access control
- SensitivityLevel: S1/S2/S3 privacy classification
- PIIAction: warn / redact / block
- PrivacyPolicy: PII protection configuration
- PrivacyRoutingConfig: privacy-aware model routing configuration
- ReviewDecision / ReviewResult / RecentToolCall / SecurityReviewerProtocol: Layer 5.5 Transcript Classifier
- SecurityConfig: complete per-session security configuration

[POS]
Foundation layer of the security type hierarchy. All other security modules
import from here; this module imports from none of them.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Capability:
    """A single capability grant or exclusion: (permission_type, resource_pattern).

    Capabilities are deny-by-default: only explicitly granted capabilities
    are allowed. Once a CapabilitySet is created, it cannot be expanded
    (anti-privilege-escalation via frozenset).

    A ``permission`` prefixed with ``!`` acts as a **negative capability**
    (exclusion). Negative capabilities take precedence over positive ones,
    enabling patterns like "allow everything except browser_*".
    """

    permission: str
    pattern: str


CapabilitySet = frozenset[Capability]

DEFAULT_CAPABILITIES: CapabilitySet = frozenset({Capability("*", "*")})


class PermissionAction(StrEnum):
    """How a tool call should be handled after permission evaluation."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """A single rule mapping (permission_type, pattern) to an action.

    ``permission`` matches tool categories (e.g. ``"shell_exec"``, ``"file_write"``, ``"*"``).
    ``pattern`` matches the target resource (e.g. ``"*.py"``, ``"api.openai.com"``, ``"*"``).
    Both use fnmatch-style wildcards.
    """

    permission: str
    pattern: str
    action: PermissionAction


PermissionRuleset = tuple[PermissionRule, ...]


DEFAULT_RULESET: PermissionRuleset = (
    PermissionRule("*", "*", PermissionAction.ALLOW),
    PermissionRule("shell_exec", "*", PermissionAction.ASK),
    PermissionRule("code_interpreter", "*", PermissionAction.ASK),
    # Sensitive files: credentials, keys, databases
    PermissionRule("file_read", "*.env", PermissionAction.ASK),
    PermissionRule("file_read", "*.env.*", PermissionAction.ASK),
    PermissionRule("file_read", "*.pem", PermissionAction.ASK),
    PermissionRule("file_read", "*.key", PermissionAction.ASK),
    PermissionRule("file_read", "*.db", PermissionAction.ASK),
    PermissionRule("file_read", "*.sqlite", PermissionAction.ASK),
    PermissionRule("file_read", "*.sqlite3", PermissionAction.ASK),
    PermissionRule("file_read", "*credentials.json", PermissionAction.ASK),
    PermissionRule("file_read", "*secrets.json", PermissionAction.ASK),
    PermissionRule("file_read", "*.git/config", PermissionAction.ASK),
    PermissionRule("file_write", "*.env", PermissionAction.ASK),
    PermissionRule("file_write", "*.env.*", PermissionAction.ASK),
    PermissionRule("file_write", "*.pem", PermissionAction.ASK),
    PermissionRule("file_write", "*.key", PermissionAction.ASK),
    PermissionRule("file_write", "*.db", PermissionAction.ASK),
    PermissionRule("file_write", "*.sqlite", PermissionAction.ASK),
    PermissionRule("file_write", "*.sqlite3", PermissionAction.ASK),
    PermissionRule("file_write", "*credentials.json", PermissionAction.ASK),
    PermissionRule("file_write", "*secrets.json", PermissionAction.ASK),
    PermissionRule("file_write", "*.git/config", PermissionAction.ASK),
    PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
    PermissionRule("browser_evaluate", "*", PermissionAction.DENY),
    PermissionRule("browser_upload", "*", PermissionAction.ASK),
    PermissionRule("browser_download", "*", PermissionAction.ASK),
    PermissionRule("browser_fill", "*", PermissionAction.ASK),
    PermissionRule("browser_session", "*", PermissionAction.ASK),
    PermissionRule("browser_human_handover", "*", PermissionAction.ASK),
    PermissionRule("browser_navigate", "127.0.0.1*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "localhost*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "0.0.0.0*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "10.*", PermissionAction.DENY),
    # RFC 1918: 172.16.0.0/12 = 172.16.* ~ 172.31.*
    PermissionRule("browser_navigate", "172.16.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.17.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.18.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.19.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.20.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.21.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.22.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.23.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.24.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.25.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.26.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.27.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.28.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.29.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.30.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "172.31.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "192.168.*", PermissionAction.DENY),
    PermissionRule("browser_navigate", "169.254.*", PermissionAction.DENY),
    PermissionRule("desktop_control", "*", PermissionAction.ASK),
    PermissionRule("skill_manage", "*", PermissionAction.ASK),
    PermissionRule("cron_manage", "*", PermissionAction.ASK),
    PermissionRule("delegate_agent", "*", PermissionAction.ALLOW),
)


class SensitivityLevel(StrEnum):
    """Three-tier privacy classification for content.

    S1: public — safe to send to cloud LLM, no action needed.
    S2: sensitive — contains PII (phone, email, etc.), action per policy.
    S3: confidential — contains strong-sensitive data (ID card, bank card,
        API keys), must be redacted or blocked.
    """

    S1 = "s1"
    S2 = "s2"
    S3 = "s3"


class PIIAction(StrEnum):
    """How to handle content at a given sensitivity level.

    WARN: log but do not alter content.
    REDACT: irreversibly mask PII (e.g. 138****8000). AI loses semantic info.
    PSEUDONYMIZE: reversibly replace PII with typed placeholders
        (e.g. <PHONE_NUMBER_1>). AI retains semantic understanding,
        original values restored locally before user sees the response.
    BLOCK: reject the message entirely.
    """

    WARN = "warn"
    REDACT = "redact"
    PSEUDONYMIZE = "pseudonymize"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """PII protection configuration for an Agent session.

    Controls whether PII detection is active, which actions to take for
    S2/S3 content, and optional custom keywords/patterns/tools/paths
    that extend the built-in detection rules.

    When ``deep_scan`` is True, an LLM-based detector supplements the
    regex engine to catch non-structured PII (medical history, family
    relations, workplace, etc.) that regex cannot match.
    """

    enabled: bool = False
    s2_action: PIIAction = PIIAction.WARN
    s3_action: PIIAction = PIIAction.REDACT
    deep_scan: bool = False
    custom_keywords_s2: tuple[str, ...] = ()
    custom_keywords_s3: tuple[str, ...] = ()
    custom_patterns_s2: tuple[str, ...] = ()
    custom_patterns_s3: tuple[str, ...] = ()
    sensitive_tools_s2: tuple[str, ...] = ()
    sensitive_tools_s3: tuple[str, ...] = ()
    sensitive_paths_s3: tuple[str, ...] = (
        ".env",
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    )


@dataclass(frozen=True, slots=True)
class PrivacyRoutingConfig:
    """Privacy-aware model routing configuration.

    Controls how the PrivacyRoutingModel selects between cloud and local
    models based on the detected sensitivity level.

    When ``local_model`` is None, routing is disabled and all requests
    go to the cloud model (transparent pass-through).
    """

    local_model: str | None = None
    local_base_url: str | None = None
    local_api_key: str | None = None
    s2_strategy: Literal["cloud_after_redact", "local"] = "cloud_after_redact"
    s3_strategy: Literal["local", "block"] = "local"
    local_fallback: Literal["block", "force_redact_cloud"] = "block"


def _default_privacy_policy() -> PrivacyPolicy:
    return PrivacyPolicy()


def _default_dangerous_paths() -> frozenset[str]:
    from myrm_agent_harness.core.security.path_security import DANGEROUS_PATHS

    return DANGEROUS_PATHS


@dataclass(frozen=True, slots=True)
class PathPolicy:
    """Path-level access control for file operations.

    Three-layer check: forbidden → allowed_roots → workspace.
    forbidden_paths always wins (cannot be overridden by allowed_roots).

    Default forbidden_paths comes from ``security.path_security.DANGEROUS_PATHS``
    (single source of truth for all path-based security).

    ``workspace_label`` is an optional human-readable label for the workspace
    (e.g., "My Projects", "Work") used by the GUI to display workspace context.
    """

    forbidden_paths: frozenset[str] = field(default_factory=_default_dangerous_paths)
    allowed_roots: tuple[str, ...] = ()
    workspace_label: str | None = None


def _default_path_policy() -> PathPolicy:
    return PathPolicy()


class ReviewDecision(StrEnum):
    """LLM security reviewer decision for a shell command."""

    ALLOW = "allow"
    DENY = "deny"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Result from a security reviewer evaluation."""

    decision: ReviewDecision
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecentToolCall:
    """Compact representation of a recent tool call for transcript context.

    Only tool_name and args are included (Reasoning-Blind: no assistant
    text, no tool output, no descriptions).
    """

    tool_name: str
    args: dict[str, object]


@runtime_checkable
class SecurityReviewerProtocol(Protocol):
    """6th framework protocol — LLM-based Transcript Classifier for auto-mode.

    Invoked when the deterministic security engine cannot classify a tool call
    (returns ASK) and ``auto_mode_enabled`` is True. The classifier examines
    user intent + recent tool call sequence (Reasoning-Blind) to decide
    whether the action is safe to auto-execute.

    Implementations must be fail-safe: any exception or timeout should be
    treated as UNCERTAIN, causing fallback to HITL approval.
    """

    async def review(
        self,
        command: str,
        *,
        workspace_root: str | None = None,
        intent_context: str | None = None,
        taint_labels: frozenset[str] | None = None,
        recent_tool_calls: tuple[RecentToolCall, ...] = (),
        model_id: str | None = None,
        trusted_domains: tuple[str, ...] = (),
    ) -> ReviewResult:
        """Evaluate whether a tool call is safe to auto-execute.

        Args:
            command: String representation of the tool call to evaluate.
            workspace_root: Current working directory context.
            intent_context: Recent human messages representing the user's intent
                (Reasoning-Blind: only user messages, no assistant text).
            taint_labels: Taint labels currently active in the session.
            recent_tool_calls: Recent tool call sequence for cross-tool context.
            model_id: Optional ID of the specific LLM model to use.
            trusted_domains: Domains the user has explicitly marked as trusted
                (from network_allowlist). Helps distinguish internal vs external.

        Returns:
            ReviewResult with ALLOW, DENY, or UNCERTAIN decision.
        """
        ...


@dataclass(frozen=True, slots=True)
class SecurityConfig:
    """Complete security configuration for an Agent session.

    Evaluation order in ``engine.evaluate_tool_call``:
    1. Capability Fence (deny-by-default, anti-privilege-escalation)
    2a. Shell Command Analyzer (BLOCK → DENY, ESCALATE → ASK)
    2b. URL Scheme Check (browser_navigate: only http/https allowed)
    2c. Domain HITL (URL-bearing tools: domain not in allowlist → ASK)
    3. Path Policy (forbidden → allowed_roots → workspace, file ops only)
    4. Permission ruleset with target resolution (last-match-wins)
    5. Risk classifier fallback (SAFE shell commands → ALLOW)
    5.5. Transcript Classifier (all ASK operations, when auto_mode_enabled) → ALLOW/DENY/UNCERTAIN
    6. Fallback to ASK if no rule matches
    """

    capabilities: CapabilitySet = field(default=DEFAULT_CAPABILITIES)
    ruleset: PermissionRuleset = field(default=DEFAULT_RULESET)
    approval_timeout_seconds: int = 120
    approval_timeout_behavior: str = "deny"
    path_policy: PathPolicy = field(default_factory=_default_path_policy)
    network_allowlist: tuple[str, ...] = ()
    network_blocklist: tuple[str, ...] = ()
    domain_hitl_enabled: bool = True
    privacy_policy: PrivacyPolicy = field(default_factory=_default_privacy_policy)
    auto_mode_enabled: bool = False
    auto_review_model: str | None = None
    auto_review_timeout_seconds: float = 3.0
    transcript_window_size: int = 20
    plan_confirm_enabled: bool = False
    yolo_mode_enabled: bool = False
    yolo_mode_enabled_at: float | None = None
    yolo_mode_timeout: int | None = None

    # ------------------------------------------------------------------
    # Factory methods — pre-built profiles for common security postures
    # ------------------------------------------------------------------

    @classmethod
    def readonly(
        cls,
        *,
        allowed_roots: tuple[str, ...] = (),
        workspace_label: str | None = None,
    ) -> SecurityConfig:
        """Read-only profile: no file writes, no shell, no browser mutations.

        Suitable for data-analysis or research agents that only need to read
        files and browse the web without side effects.
        """
        read_only_rules: PermissionRuleset = (
            PermissionRule("*", "*", PermissionAction.ALLOW),
            PermissionRule("file_write", "*", PermissionAction.DENY),
            PermissionRule("file_edit", "*", PermissionAction.DENY),
            PermissionRule("file_delete", "*", PermissionAction.DENY),
            PermissionRule("shell_exec", "*", PermissionAction.DENY),
            PermissionRule("code_interpreter", "*", PermissionAction.DENY),
            PermissionRule("browser_evaluate", "*", PermissionAction.DENY),
            PermissionRule("browser_fill", "*", PermissionAction.DENY),
            PermissionRule("browser_upload", "*", PermissionAction.DENY),
            PermissionRule("browser_download", "*", PermissionAction.DENY),
            PermissionRule("skill_manage", "*", PermissionAction.DENY),
            PermissionRule("cron_manage", "*", PermissionAction.DENY),
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
            PermissionRule("delegate_agent", "*", PermissionAction.ALLOW),
        )
        return cls(
            capabilities=frozenset({Capability("*", "*")}),
            ruleset=read_only_rules,
            path_policy=PathPolicy(allowed_roots=allowed_roots, workspace_label=workspace_label),
        )

    @classmethod
    def workspace(
        cls,
        *,
        allowed_roots: tuple[str, ...],
        shell_action: PermissionAction = PermissionAction.ASK,
        workspace_label: str | None = None,
    ) -> SecurityConfig:
        """Workspace-scoped profile: file ops constrained to *allowed_roots*.

        Shell execution defaults to ASK (human approval required).
        Browser mutations require approval. Network access is unrestricted.
        """
        workspace_rules: PermissionRuleset = (
            PermissionRule("*", "*", PermissionAction.ALLOW),
            PermissionRule("shell_exec", "*", shell_action),
            PermissionRule("code_interpreter", "*", PermissionAction.ASK),
            PermissionRule("browser_evaluate", "*", PermissionAction.DENY),
            PermissionRule("browser_upload", "*", PermissionAction.ASK),
            PermissionRule("browser_download", "*", PermissionAction.ASK),
            PermissionRule("browser_fill", "*", PermissionAction.ASK),
            PermissionRule("skill_manage", "*", PermissionAction.ASK),
            PermissionRule("cron_manage", "*", PermissionAction.ASK),
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
            PermissionRule("delegate_agent", "*", PermissionAction.ALLOW),
        )
        return cls(
            capabilities=frozenset({Capability("*", "*")}),
            ruleset=workspace_rules,
            path_policy=PathPolicy(allowed_roots=allowed_roots, workspace_label=workspace_label),
        )

    @classmethod
    def full_access(cls) -> SecurityConfig:
        """Full-access profile: all operations allowed, YOLO mode enabled.

        For trusted local environments where the user accepts all risks.
        Equivalent to disabling the security subsystem.
        """
        full_rules: PermissionRuleset = (PermissionRule("*", "*", PermissionAction.ALLOW),)
        return cls(
            capabilities=frozenset({Capability("*", "*")}),
            ruleset=full_rules,
            yolo_mode_enabled=True,
        )

    @classmethod
    def remote_exposed(cls) -> SecurityConfig:
        """Remote-exposed admission overlay: deny destructive and computer-use tools."""
        remote_rules: PermissionRuleset = (
            PermissionRule("shell_exec", "*", PermissionAction.DENY),
            PermissionRule("code_interpreter", "*", PermissionAction.DENY),
            PermissionRule("desktop_control", "*", PermissionAction.DENY),
            PermissionRule("browser_upload", "*", PermissionAction.DENY),
            PermissionRule("browser_download", "*", PermissionAction.DENY),
            PermissionRule("browser_fill", "*", PermissionAction.DENY),
            PermissionRule("browser_evaluate", "*", PermissionAction.DENY),
            PermissionRule("skill_manage", "*", PermissionAction.DENY),
            PermissionRule("cron_manage", "*", PermissionAction.DENY),
            PermissionRule("mcp_invoke", "*", PermissionAction.ASK),
            PermissionRule("delegate_agent", "*", PermissionAction.DENY),
        )
        return cls(
            capabilities=frozenset({Capability("*", "*")}),
            ruleset=remote_rules,
            yolo_mode_enabled=False,
        )


@dataclass(frozen=True, slots=True)
class EphemeralUserCredential:
    """User-session-affinity credential context for enterprise integrations and SaaS.

    Ephemerally bound to the active coroutine context using ContextVar. Passed down
    from the business layer (myrm-agent-server) to propagate user OAuth tokens into
    tool execution paths (like sub-processes or HTTP requests) without storing them
    in the database or global system environment variables.
    """

    issuer: str  # Identifies the system/provider (e.g. "feishu", "dingtalk", "github")
    token: str  # Ephemeral Token (OAuth user_access_token or PAT)
    scope: str = ""  # Authorized Scope of the token
    user_id: str = ""  # External system user identifier
    expires_at: float | None = None  # Ephemeral expiry time in monotonic/epoch seconds
    refresh_callback: Callable[[], Awaitable[EphemeralUserCredential | None]] | None = (
        None  # Optional callback to refresh expired token
    )


# Session-bound user credentials context variable. Managed per coroutine.
user_credentials_ctx: ContextVar[tuple[EphemeralUserCredential, ...]] = ContextVar("user_credentials_ctx", default=())


@asynccontextmanager
async def with_user_credentials(
    credentials: tuple[EphemeralUserCredential, ...],
) -> AsyncIterator[None]:
    """Async context manager to safely inject and automatically clean up user credentials.

    Ensures that credentials are bound only to the specific async execution block.
    """
    token_ctx = user_credentials_ctx.set(credentials)
    try:
        yield
    finally:
        user_credentials_ctx.reset(token_ctx)


def propagate_user_credentials[P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Capture the current context (including user_credentials_ctx) and return a wrapped function.

    When called from any other thread, background worker, or pool, the wrapped function
    executes inside the captured context, ensuring no user credentials are lost.
    """
    try:
        credentials = user_credentials_ctx.get()
    except LookupError:
        credentials = ()

    if inspect.iscoroutinefunction(fn):

        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            token_ctx = user_credentials_ctx.set(credentials)
            try:
                return await fn(*args, **kwargs)
            finally:
                user_credentials_ctx.reset(token_ctx)

        return async_wrapper  # type: ignore

    ctx = copy_context()

    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return ctx.run(fn, *args, **kwargs)

    return sync_wrapper


class ToolClarificationException(Exception):  # noqa: N818  intentional descriptive name (HITL, cross-repo)
    """Raised when a tool needs human clarification before proceeding.

    Used by HITL (Human-in-the-Loop) tools that require the user to
    disambiguate or confirm parameters (e.g., selecting exact user IDs
    from ambiguous names).
    """
