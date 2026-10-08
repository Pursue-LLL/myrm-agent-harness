"""Types and schemas for SSO Redirect Idempotence and Probe Hysteresis.

Provides data structures for safe navigation targets, idempotent SSO redirect
URLs, and desktop/agent network probe hysteresis state evaluation.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ALLOWED_DEEP_LINK_SCHEMES: frozenset[str] = frozenset(
    {"myrm", "myrm-desktop", "ihui"}
)


class SafeNavigationOptions(BaseModel):
    """Options governing safe redirect target navigation decisions."""

    model_config = ConfigDict(frozen=True)

    allow_deep_link: bool = Field(
        default=False,
        description="Whether custom protocol deep links (e.g. myrm://) are permitted",
    )
    allowed_deep_link_schemes: frozenset[str] = Field(
        default=DEFAULT_ALLOWED_DEEP_LINK_SCHEMES,
        description="Permitted deep link URL scheme prefixes",
    )
    allowed_origins: tuple[str, ...] | None = Field(
        default=None,
        description="Optional whitelist of trusted origins for absolute HTTP/HTTPS targets",
    )
    fallback_url: str = Field(
        default="/",
        description="Default fallback relative URL when target is deemed unsafe",
    )


class SsoRedirectResult(BaseModel):
    """Result of constructing an idempotent SSO redirect URL."""

    model_config = ConfigDict(frozen=True)

    original_uri: str
    redirect_url: str
    stripped_existing_code: bool
    is_relative: bool
    is_safe_target: bool


@dataclass(frozen=True)
class ProbeHysteresisConfig:
    """Configuration for probe health hysteresis dampening."""

    consecutive_fail_threshold: int = 3
    probe_attempts_per_round: int = 2
    probe_retry_gap_seconds: float = 2.0
    offline_fallback_url: str = "/offline"


class ProbeEvaluation(BaseModel):
    """Evaluation result of network health with hysteresis dampening."""

    model_config = ConfigDict(frozen=True)

    is_online: bool
    transitioned_to_offline: bool
    transitioned_to_online: bool
    consecutive_fails: int
    last_healthy_url: str | None
    suggested_navigation_url: str
