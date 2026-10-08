"""Validation and policy engine for Admin Authentication Surface.

[INPUT]
- AdminAuthSurfaceConfig configuration models.

[OUTPUT]
- AuthSurfaceValidationResult: Validity status, active method count, and deadlock error diagnostics.

[POS]
Validator evaluating anti-lockout invariants and consistency rules for authentication surface settings.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.admin_auth_surface.types import (
    AdminAuthSurfaceConfig,
    AuthSurfaceValidationResult,
)


class AdminAuthSurfaceValidator:
    """Validates unified authentication surface configuration consistency."""

    @classmethod
    def validate(cls, config: AdminAuthSurfaceConfig) -> AuthSurfaceValidationResult:
        """Validate an authentication configuration against deadlock and consistency rules.

        Rules enforced:
        1. Non-deadlock: At least one login method must remain enabled (password, email code, or active OAuth).
        2. Auto-registration prerequisite: email_code_auto_registration_enabled requires email_code_enabled.
        3. OAuth integrity: active OAuth connections must have non-empty client_id, authorize_url, and token_url.
        """
        errors: list[str] = []
        warnings: list[str] = []

        active_oauth_count = sum(1 for conn in config.oauth_connections if conn.enabled)
        active_primary_methods = 0

        if config.login_methods.password_enabled:
            active_primary_methods += 1
        if config.login_methods.email_code_enabled:
            active_primary_methods += 1

        total_active_methods = active_primary_methods + active_oauth_count

        # Rule 1: No lockout / deadlock
        if total_active_methods == 0:
            errors.append(
                "Deadlock condition: At least one authentication method (password, email code, or enabled OAuth) must be enabled."
            )

        # Rule 2: Prerequisite check
        if (
            config.login_methods.email_code_auto_registration_enabled
            and not config.login_methods.email_code_enabled
        ):
            errors.append(
                "Inconsistent settings: Email code auto-registration cannot be enabled when email code login is disabled."
            )

        # Rule 3: OAuth validation
        for conn in config.oauth_connections:
            if conn.enabled:
                if not conn.client_id.strip():
                    errors.append(
                        f"OAuth connection '{conn.id}' missing required client_id."
                    )
                if not conn.authorize_url.strip():
                    errors.append(
                        f"OAuth connection '{conn.id}' missing required authorize_url."
                    )
                if not conn.token_url.strip():
                    errors.append(
                        f"OAuth connection '{conn.id}' missing required token_url."
                    )

        if (
            not config.login_methods.password_enabled
            and active_primary_methods == 0
            and active_oauth_count > 0
        ):
            warnings.append(
                "Password login is disabled. System relies exclusively on third-party OAuth providers."
            )

        return AuthSurfaceValidationResult(
            is_valid=len(errors) == 0,
            active_login_method_count=total_active_methods,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def mask_secret(secret: str) -> str:
        """Mask OAuth client secret for safe display on admin surfaces."""
        if not secret:
            return ""
        if len(secret) <= 4:
            return "****"
        return f"{secret[:2]}****{secret[-2:]}"

    @staticmethod
    def is_masked_secret(secret: str) -> bool:
        """Check if secret representation is masked or placeholder."""
        if not secret or not secret.strip():
            return True
        return "****" in secret or secret.startswith("**")
