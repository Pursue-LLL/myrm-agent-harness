"""
[POS] src/myrm_agent_harness/core/security/case_variant_scrubber/facade.py
[INPUT] typing
[OUTPUT] CaseVariantScrubberSuite

Unified facade for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .case_folded_scrubber import CaseFoldedCredentialScrubber
from .oauth_pkce_seam import OAuthPKCESeam
from .types import (
    OAuthPKCEState,
    OAuthProviderManifest,
    ScrubActionEnum,
    ScrubAuditReport,
    ScrubberSuiteMetrics,
)

logger = logging.getLogger(__name__)


class CaseVariantScrubberSuite:
    """Unified facade orchestrating case-variant credential scrubbing and declarative OAuth PKCE."""

    def __init__(
        self,
        custom_patterns: tuple[str, ...] | None = None,
        initial_providers: tuple[OAuthProviderManifest, ...] | None = None,
    ) -> None:
        self._scrubber = CaseFoldedCredentialScrubber(custom_patterns=custom_patterns)
        self._pkce_seam = OAuthPKCESeam(initial_providers=initial_providers)
        self._metrics = ScrubberSuiteMetrics()

    @property
    def metrics(self) -> ScrubberSuiteMetrics:
        """Read-only operational metrics."""
        return self._metrics

    def scrub_environment(
        self,
        env_dict: dict[str, str],
        action: ScrubActionEnum = ScrubActionEnum.DROP,
        whitelist: set[str] | None = None,
    ) -> tuple[dict[str, str], ScrubAuditReport]:
        """Deeply scrub environment dictionary and record metrics."""
        clean_env, report = self._scrubber.scrub_env(
            env_dict=env_dict,
            action=action,
            whitelist=whitelist,
        )
        self._metrics.envs_scrubbed_total += 1
        self._metrics.credentials_intercepted_total += report.total_dropped + report.total_redacted
        self._metrics.injections_detected_total += len(report.detected_injections)
        return clean_env, report

    def detect_injections(self, env_dict: dict[str, str]) -> list[str]:
        """Check for suspicious case-variant credential injection attempts."""
        return self._scrubber.detect_injection_attempts(env_dict)

    def initiate_pkce_flow(
        self,
        provider_id: str,
        redirect_uri: str,
        ttl_seconds: float = 600.0,
    ) -> tuple[OAuthPKCEState, str]:
        """Initiate OAuth 2.0 PKCE challenge flow and generate authorization URL."""
        state, url = self._pkce_seam.initiate_flow(
            provider_id=provider_id,
            redirect_uri=redirect_uri,
            ttl_seconds=ttl_seconds,
        )
        self._metrics.pkce_flows_initiated_total += 1
        return state, url

    def exchange_pkce_token(
        self,
        flow_id: str,
        auth_code: str,
        incoming_state: str,
    ) -> dict[str, str]:
        """Validate PKCE invariants and generate token exchange payload."""
        payload = self._pkce_seam.validate_and_prepare_exchange(
            flow_id=flow_id,
            auth_code=auth_code,
            incoming_state=incoming_state,
        )
        self._metrics.pkce_tokens_exchanged_total += 1
        return payload

    def register_oauth_provider(self, manifest: OAuthProviderManifest) -> None:
        """Register declarative external model provider."""
        self._pkce_seam.register_provider(manifest)

    def list_oauth_providers(self) -> list[OAuthProviderManifest]:
        """List registered OAuth provider manifests."""
        return self._pkce_seam.list_providers()
