"""Manager implementing authentication surface invariants and lifecycle governance.

[INPUT]
- AdminAuthSurfaceConfig and incoming update payloads.

[OUTPUT]
- Validated, sanitized configurations and Anti-Lockout validation results.

[POS]
- Core security engine enforcing anti-lockout safety rules and credential masking
  for the unified admin authentication surface.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.admin_auth_surface.types import (
    AdminAuthSurfaceConfig,
    AuthSurfaceValidationResult,
    LoginMethodSettings,
    OAuthConnectionConfig,
)
from myrm_agent_harness.core.security.admin_auth_surface.validator import (
    AdminAuthSurfaceValidator,
)

MASKED_SECRET_PLACEHOLDER: str = "******"


class AdminAuthSurfaceManager:
    """Manages system authentication surface policies and anti-lockout invariants."""

    def __init__(
        self,
        initial_config: AdminAuthSurfaceConfig | None = None,
    ) -> None:
        """Initialize manager with baseline configuration."""
        self._config = initial_config or AdminAuthSurfaceConfig()

    def get_config(self) -> AdminAuthSurfaceConfig:
        """Return raw active configuration."""
        return self._config

    def get_masked_config(self) -> AdminAuthSurfaceConfig:
        """Return configuration with sensitive OAuth secrets masked."""
        masked_connections = [
            OAuthConnectionConfig(
                id=c.id,
                provider=c.provider,
                name=c.name,
                client_id=c.client_id,
                client_secret=AdminAuthSurfaceValidator.mask_secret(
                    c.client_secret
                ),
                authorize_url=c.authorize_url,
                token_url=c.token_url,
                scopes=list(c.scopes),
                issuer_url=c.issuer_url,
                enabled=c.enabled,
                auto_registration_enabled=c.auto_registration_enabled,
            )
            for c in self._config.oauth_connections
        ]

        return AdminAuthSurfaceConfig(
            login_methods=self._config.login_methods,
            oauth_connections=masked_connections,
            allow_public_registration=self._config.allow_public_registration,
            mfa_enforced=self._config.mfa_enforced,
        )

    @staticmethod
    def validate_config(
        config: AdminAuthSurfaceConfig,
    ) -> AuthSurfaceValidationResult:
        """Validate safety rules and anti-lockout invariants on configuration."""
        return AdminAuthSurfaceValidator.validate(config)

    def update_config(
        self,
        candidate_config: AdminAuthSurfaceConfig,
        preserve_masked_secrets: bool = True,
    ) -> tuple[AdminAuthSurfaceConfig, AuthSurfaceValidationResult]:
        """Validate and apply a new authentication surface configuration.

        Args:
            candidate_config: Desired configuration update.
            preserve_masked_secrets: Whether to preserve original secrets when masked.

        Returns:
            Tuple of (effective_config, validation_result).

        Raises:
            ValueError: If candidate config violates anti-lockout invariants.
        """
        existing_secrets: dict[str, str] = {
            c.id: c.client_secret for c in self._config.oauth_connections
        }

        merged_connections: list[OAuthConnectionConfig] = []
        for c in candidate_config.oauth_connections:
            secret = c.client_secret
            if preserve_masked_secrets and AdminAuthSurfaceValidator.is_masked_secret(secret):
                secret = existing_secrets.get(c.id, "")


            merged_connections.append(
                OAuthConnectionConfig(
                    id=c.id,
                    provider=c.provider,
                    name=c.name,
                    client_id=c.client_id,
                    client_secret=secret,
                    authorize_url=c.authorize_url,
                    token_url=c.token_url,
                    scopes=list(c.scopes),
                    issuer_url=c.issuer_url,
                    enabled=c.enabled,
                    auto_registration_enabled=c.auto_registration_enabled,
                )
            )

        resolved_config = AdminAuthSurfaceConfig(
            login_methods=LoginMethodSettings(
                password_enabled=candidate_config.login_methods.password_enabled,
                email_code_enabled=(
                    candidate_config.login_methods.email_code_enabled
                ),
                email_code_auto_registration_enabled=(
                    candidate_config.login_methods.email_code_auto_registration_enabled
                ),
            ),
            oauth_connections=merged_connections,
            allow_public_registration=(
                candidate_config.allow_public_registration
            ),
            mfa_enforced=candidate_config.mfa_enforced,
        )

        validation = self.validate_config(resolved_config)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))

        self._config = resolved_config
        return self._config, validation
