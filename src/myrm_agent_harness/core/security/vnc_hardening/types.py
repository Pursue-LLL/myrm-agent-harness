"""
[POS] src/myrm_agent_harness/core/security/vnc_hardening/types.py
[INPUT] enum, typing, pydantic
[OUTPUT] VncBindMode, VncAuthPolicy, VncSecurityViolationType, VncSecurityAuditViolation,
         VncLaunchConfig, VncHardenedLaunchSpec, VncHardeningAuditReport
Core domain types for VNC loopback bind and rfbauth hardening suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class VncBindMode(StrEnum):
    """Network binding scope for native VNC / x11vnc server."""

    LOOPBACK = "loopback"
    NON_LOOPBACK_OPT_IN = "non_loopback_opt_in"


class VncAuthPolicy(StrEnum):
    """Authentication policy enforced on native RFB endpoint."""

    RFBAUTH_MANDATORY = "rfbauth_mandatory"


class VncSecurityViolationType(StrEnum):
    """Taxonomy of VNC native binding and authentication security violations."""

    NOPW_CONFLICT = "nopw_conflict"
    UNPROTECTED_NON_LOOPBACK = "unprotected_non_loopback"
    INSECURE_PASSWORD = "insecure_password"
    MISSING_RFBAUTH = "missing_rfbauth"
    INSECURE_PASSWD_FILE_PERMS = "insecure_passwd_file_perms"
    UNSANITIZED_FLAGS = "unsanitized_flags"


class VncSecurityAuditViolation(BaseModel):
    """Structured security audit violation detected in VNC configuration or runtime."""

    violation_type: VncSecurityViolationType = Field(..., description="Classification of security violation")
    description: str = Field(..., description="Human-readable rationale and threat explanation")
    flag_or_path: str = Field(..., description="Conflicting command line flag, parameter, or filepath")
    auto_remediated: bool = Field(default=False, description="Whether this violation was automatically sanitized")


class VncLaunchConfig(BaseModel):
    """Raw configuration parameters intended to launch an x11vnc native instance."""

    display_num: int = Field(default=0, ge=0, description="X11 display number, e.g. 0 for :0")
    vnc_port: int = Field(default=5900, ge=1024, le=65535, description="Native RFB listening port")
    passwd_file: str = Field(..., min_length=1, description="Path to rfbauth encrypted password file")
    bind_mode: VncBindMode = Field(default=VncBindMode.LOOPBACK, description="Intended network bind mode")
    non_loopback_opt_in: bool = Field(
        default=False,
        description="Explicit administrator opt-in flag required for non-loopback exposure",
    )
    opt_in_password: str | None = Field(
        default=None,
        description="Password required when requesting explicit non-loopback bind",
    )
    extra_flags: list[str] = Field(default_factory=list, description="Additional x11vnc command line flags")


class VncHardenedLaunchSpec(BaseModel):
    """Enforced, sanitized command line specification for launching x11vnc securely."""

    command_args: list[str] = Field(..., description="Final hardened command line tokens for exec")
    effective_bind_mode: VncBindMode = Field(..., description="Enforced effective binding mode")
    rfbauth_path: str = Field(..., description="Enforced rfbauth credential file path")
    violations: list[VncSecurityAuditViolation] = Field(
        default_factory=list,
        description="Security violations detected and remediated during sanitization",
    )
    is_hardened: bool = Field(default=True, description="Whether spec complies with zero-trust baseline")


class VncHardeningAuditReport(BaseModel):
    """Comprehensive compliance evaluation report for VNC launch parameters."""

    timestamp: float = Field(..., description="Audit evaluation epoch timestamp")
    spec: VncHardenedLaunchSpec = Field(..., description="Evaluated hardened launch specification")
    verdict: str = Field(..., description="Audit verdict: PASS or BLOCKED")
    remediation_summary: list[str] = Field(
        default_factory=list,
        description="Summary of auto-remediation steps applied to secure the instance",
    )
