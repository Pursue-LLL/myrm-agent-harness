"""
[POS] src/myrm_agent_harness/core/security/case_variant_scrubber/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ScrubActionEnum, OAuthPKCEChallengeMethod, ScrubbedEnvRecord, ScrubAuditReport, OAuthPKCEState, OAuthProviderManifest, ScrubberSuiteMetrics

Data structures and specifications for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScrubActionEnum(StrEnum):
    """Action applied to matching credential environment variables."""

    DROP = "DROP"
    REDACT_PLACEHOLDER = "REDACT_PLACEHOLDER"
    ALLOW_PASSTHROUGH = "ALLOW_PASSTHROUGH"


class OAuthPKCEChallengeMethod(StrEnum):
    """PKCE code challenge transformation method per RFC 7636."""

    S256 = "S256"
    PLAIN = "plain"


@dataclass(frozen=True)
class ScrubbedEnvRecord:
    """Descriptor of an environment variable identified and scrubbed."""

    original_key: str
    folded_key: str
    action: ScrubActionEnum
    matched_pattern: str
    redacted_value: str


@dataclass(frozen=True)
class ScrubAuditReport:
    """Audit report generated after deep scrubbing of environment dictionary."""

    total_scanned: int
    total_dropped: int
    total_redacted: int
    scrubbed_records: tuple[ScrubbedEnvRecord, ...]
    detected_injections: tuple[str, ...]
    timestamp: float


@dataclass(frozen=True)
class OAuthPKCEState:
    """Ephemeral state object tracking in-flight OAuth 2.0 PKCE challenge."""

    flow_id: str
    provider_id: str
    state_token: str
    code_verifier: str
    code_challenge: str
    challenge_method: OAuthPKCEChallengeMethod
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class OAuthProviderManifest:
    """Declarative specification for external model provider OAuth 2.0 PKCE integration."""

    provider_id: str
    display_name: str
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    scopes: tuple[str, ...]
    challenge_method: OAuthPKCEChallengeMethod = OAuthPKCEChallengeMethod.S256


@dataclass
class ScrubberSuiteMetrics:
    """Cumulative operational metrics for credential scrubbing and PKCE flows."""

    envs_scrubbed_total: int = 0
    credentials_intercepted_total: int = 0
    injections_detected_total: int = 0
    pkce_flows_initiated_total: int = 0
    pkce_tokens_exchanged_total: int = 0
