"""
[POS] src/myrm_agent_harness/core/security/vnc_hardening/config_sanitizer.py
[INPUT] typing, types, passwd_manager
[OUTPUT] VncLaunchConfigSanitizer
Sanitizer for x11vnc launch arguments enforcing -localhost default, -nopw removal, and rfbauth.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .passwd_manager import VncPasswdManager, VncSecurityError
from .types import (
    VncBindMode,
    VncHardenedLaunchSpec,
    VncLaunchConfig,
    VncSecurityAuditViolation,
    VncSecurityViolationType,
)

logger = logging.getLogger(__name__)


class VncLaunchConfigSanitizer:
    """Sanitizes x11vnc configuration parameters and synthesizes a hardened launch command."""

    def __init__(self, passwd_manager: VncPasswdManager | None = None) -> None:
        self._passwd_mgr = passwd_manager or VncPasswdManager()

    def sanitize(
        self,
        config: VncLaunchConfig,
        auto_remediate: bool = True,
    ) -> VncHardenedLaunchSpec:
        """Sanitize launch configuration and produce a hardened launch specification."""
        violations: list[VncSecurityAuditViolation] = []

        # 1. Inspect password file specification
        if not config.passwd_file.strip():
            violation = VncSecurityAuditViolation(
                violation_type=VncSecurityViolationType.MISSING_RFBAUTH,
                description="Mandatory rfbauth password file path is missing or empty",
                flag_or_path="",
                auto_remediated=False,
            )
            violations.append(violation)
            raise VncSecurityError("VNC launch requires a valid -rfbauth password file")

        # 2. Check for conflicting -nopw in extra_flags
        clean_extra_flags: list[str] = []
        for flag in config.extra_flags:
            if flag.strip() == "-nopw":
                violation = VncSecurityAuditViolation(
                    violation_type=VncSecurityViolationType.NOPW_CONFLICT,
                    description="Conflicting '-nopw' flag detected; bypasses rfbauth password protection",
                    flag_or_path="-nopw",
                    auto_remediated=auto_remediate,
                )
                violations.append(violation)
                if not auto_remediate:
                    raise VncSecurityError("Conflicting '-nopw' flag detected; prohibited under hardened policy")
                logger.warning("Stripped conflicting '-nopw' flag from x11vnc invocation")
            else:
                clean_extra_flags.append(flag)

        # 3. Handle binding mode & non-loopback opt-in
        effective_bind_mode = VncBindMode.LOOPBACK
        if config.bind_mode == VncBindMode.NON_LOOPBACK_OPT_IN or config.non_loopback_opt_in:
            if not config.non_loopback_opt_in:
                violation = VncSecurityAuditViolation(
                    violation_type=VncSecurityViolationType.UNPROTECTED_NON_LOOPBACK,
                    description="Non-loopback bind requested without explicit administrative opt-in boolean",
                    flag_or_path=config.bind_mode.value,
                    auto_remediated=auto_remediate,
                )
                violations.append(violation)
                if not auto_remediate:
                    raise VncSecurityError("Non-loopback bind requires explicit non_loopback_opt_in=True")
                logger.warning("Reverting unverified non-loopback bind to secure loopback mode")
                effective_bind_mode = VncBindMode.LOOPBACK
            elif not config.opt_in_password:
                violation = VncSecurityAuditViolation(
                    violation_type=VncSecurityViolationType.UNPROTECTED_NON_LOOPBACK,
                    description="Non-loopback exposure requested without separate dedicated opt-in password",
                    flag_or_path="opt_in_password",
                    auto_remediated=auto_remediate,
                )
                violations.append(violation)
                if not auto_remediate:
                    raise VncSecurityError("Non-loopback bind requires a separate opt-in password")
                effective_bind_mode = VncBindMode.LOOPBACK
            else:
                is_valid, reason = self._passwd_mgr.evaluate_password_strength(config.opt_in_password)
                if not is_valid:
                    violation = VncSecurityAuditViolation(
                        violation_type=VncSecurityViolationType.INSECURE_PASSWORD,
                        description=f"Non-loopback opt-in password fails strength policy: {reason}",
                        flag_or_path="opt_in_password",
                        auto_remediated=auto_remediate,
                    )
                    violations.append(violation)
                    if not auto_remediate:
                        raise VncSecurityError(f"Insecure opt-in password: {reason}")
                    effective_bind_mode = VncBindMode.LOOPBACK
                else:
                    effective_bind_mode = VncBindMode.NON_LOOPBACK_OPT_IN

        # 4. Check on-disk password file permissions if present
        passwd_p = Path(config.passwd_file)
        if passwd_p.exists():
            perm_ok, perm_msg = self._passwd_mgr.inspect_and_harden_file_permissions(passwd_p)
            if not perm_ok:
                violations.append(
                    VncSecurityAuditViolation(
                        violation_type=VncSecurityViolationType.INSECURE_PASSWD_FILE_PERMS,
                        description=perm_msg,
                        flag_or_path=str(passwd_p),
                        auto_remediated=False,
                    )
                )

        # 5. Build hardened x11vnc argument list
        cmd: list[str] = [
            "x11vnc",
            "-display",
            f":{config.display_num}",
            "-rfbport",
            str(config.vnc_port),
            "-rfbauth",
            str(config.passwd_file),
        ]

        if effective_bind_mode == VncBindMode.LOOPBACK:
            cmd.append("-localhost")

        # Standard safe flags if not already provided
        standard_defaults = ["-shared", "-forever", "-noxdamage", "-cursor", "arrow", "-quiet"]
        idx = 0
        while idx < len(standard_defaults):
            flag = standard_defaults[idx]
            if flag not in clean_extra_flags:
                cmd.append(flag)
                if flag == "-cursor" and idx + 1 < len(standard_defaults):
                    cmd.append(standard_defaults[idx + 1])
                    idx += 1
            idx += 1

        # Append remaining sanitized extra flags
        for extra in clean_extra_flags:
            if extra not in cmd and extra != "-localhost":
                cmd.append(extra)

        return VncHardenedLaunchSpec(
            command_args=cmd,
            effective_bind_mode=effective_bind_mode,
            rfbauth_path=config.passwd_file,
            violations=violations,
            is_hardened=True,
        )
