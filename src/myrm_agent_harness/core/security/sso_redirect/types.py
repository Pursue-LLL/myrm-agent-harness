"""Types and schemas for SSO Redirect Idempotency and Probe Hysteresis."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class UrlPathCategory(StrEnum):
    """Categorization of a redirect target URL."""

    SAFE_RELATIVE = "safe_relative"
    UNSAFE_RELATIVE = "unsafe_relative"
    ABSOLUTE = "absolute"
    DEEP_LINK = "deep_link"
    INVALID = "invalid"


class SsoRedirectValidation(BaseModel):
    """Result of validating a target redirect URL."""

    model_config = ConfigDict(frozen=True)

    target_url: str
    is_safe: bool
    category: UrlPathCategory
    reason: str | None = None


class SsoRedirectBuildResult(BaseModel):
    """Result of building an idempotent SSO redirect URL."""

    model_config = ConfigDict(frozen=True)

    original_url: str
    cleaned_url: str
    final_url: str
    code_attached: str
    is_relative: bool


class ProbeHysteresisState(StrEnum):
    """Hysteresis state for network and session probes."""

    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class ProbeEvaluationResult(BaseModel):
    """Result of an evaluation cycle through hysteresis filter."""

    model_config = ConfigDict(frozen=True)

    previous_state: ProbeHysteresisState
    new_state: ProbeHysteresisState
    consecutive_failures: int
    consecutive_successes: int
    state_changed: bool
    recommended_action: str
