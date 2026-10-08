"""
[POS] src/myrm_agent_harness/core/security/case_variant_scrubber/oauth_pkce_seam.py
[INPUT] base64, hashlib, logging, secrets, threading, time, urllib.parse, uuid
[OUTPUT] OAuthPKCESeam

Implements declarative OAuth 2.0 PKCE authentication flow seam according to RFC 7636.
Supports external AI model provider registration, browser challenge URLs, and code exchange validation.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
import urllib.parse

from .types import (
    OAuthPKCEChallengeMethod,
    OAuthPKCEState,
    OAuthProviderManifest,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS: tuple[OAuthProviderManifest, ...] = (
    OAuthProviderManifest(
        provider_id="openrouter",
        display_name="OpenRouter OAuth",
        authorization_endpoint="https://openrouter.ai/auth",
        token_endpoint="https://openrouter.ai/api/v1/auth/keys",
        client_id="myrm-agent-openrouter-client",
        scopes=("read", "models"),
        challenge_method=OAuthPKCEChallengeMethod.S256,
    ),
    OAuthProviderManifest(
        provider_id="github_copilot",
        display_name="GitHub Copilot Seam",
        authorization_endpoint="https://github.com/login/oauth/authorize",
        token_endpoint="https://github.com/login/oauth/access_token",
        client_id="myrm-agent-gh-copilot",
        scopes=("read:user", "copilot"),
        challenge_method=OAuthPKCEChallengeMethod.S256,
    ),
)


class OAuthPKCESeam:
    """Manages declarative OAuth 2.0 PKCE provider lifecycle and in-flight authorization flows."""

    def __init__(self, initial_providers: tuple[OAuthProviderManifest, ...] | None = None) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, OAuthProviderManifest] = {}
        self._active_flows: dict[str, OAuthPKCEState] = {}

        for p in initial_providers or DEFAULT_PROVIDERS:
            self._providers[p.provider_id] = p

    def register_provider(self, manifest: OAuthProviderManifest) -> None:
        """Register or update a declarative OAuth provider manifest."""
        with self._lock:
            self._providers[manifest.provider_id] = manifest

    def get_provider(self, provider_id: str) -> OAuthProviderManifest | None:
        """Fetch provider manifest by unique identifier."""
        with self._lock:
            return self._providers.get(provider_id)

    def list_providers(self) -> list[OAuthProviderManifest]:
        """List all currently registered OAuth provider manifests."""
        with self._lock:
            return list(self._providers.values())

    @staticmethod
    def generate_code_verifier(entropy_bytes: int = 32) -> str:
        """Generate high-entropy cryptographically random PKCE code verifier per RFC 7636."""
        return secrets.token_urlsafe(entropy_bytes)

    @classmethod
    def derive_code_challenge(
        cls,
        code_verifier: str,
        method: OAuthPKCEChallengeMethod = OAuthPKCEChallengeMethod.S256,
    ) -> str:
        """Derive base64url-encoded code challenge without padding."""
        if method == OAuthPKCEChallengeMethod.PLAIN:
            return code_verifier

        # S256: BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def initiate_flow(
        self,
        provider_id: str,
        redirect_uri: str,
        ttl_seconds: float = 600.0,
    ) -> tuple[OAuthPKCEState, str]:
        """Initiate OAuth 2.0 PKCE authorization session and return redirect URL."""
        with self._lock:
            manifest = self._providers.get(provider_id)
            if manifest is None:
                raise ValueError(f"Unknown OAuth provider: '{provider_id}'")

            flow_id = f"flow-{secrets.token_hex(8)}"
            state_token = f"state-{secrets.token_urlsafe(16)}"
            verifier = self.generate_code_verifier(32)
            challenge = self.derive_code_challenge(verifier, manifest.challenge_method)

            now = time.time()
            pkce_state = OAuthPKCEState(
                flow_id=flow_id,
                provider_id=provider_id,
                state_token=state_token,
                code_verifier=verifier,
                code_challenge=challenge,
                challenge_method=manifest.challenge_method,
                created_at=now,
                expires_at=now + ttl_seconds,
            )
            self._active_flows[flow_id] = pkce_state

            # Assemble browser redirect query parameters
            query_params: dict[str, str] = {
                "response_type": "code",
                "client_id": manifest.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(manifest.scopes),
                "state": state_token,
                "code_challenge": challenge,
                "code_challenge_method": manifest.challenge_method.value,
            }
            auth_url = f"{manifest.authorization_endpoint}?{urllib.parse.urlencode(query_params)}"
            return pkce_state, auth_url

    def validate_and_prepare_exchange(
        self,
        flow_id: str,
        auth_code: str,
        incoming_state: str,
    ) -> dict[str, str]:
        """Validate PKCE session invariants and return payload for backend token endpoint exchange."""
        with self._lock:
            state = self._active_flows.get(flow_id)
            if state is None:
                raise ValueError(f"Invalid or expired PKCE flow ID: '{flow_id}'")

            if time.time() > state.expires_at:
                self._active_flows.pop(flow_id, None)
                raise ValueError(f"PKCE flow '{flow_id}' has expired")

            if not secrets.compare_digest(state.state_token, incoming_state):
                raise ValueError("State parameter mismatch: possible CSRF or state tampering")

            manifest = self._providers.get(state.provider_id)
            if manifest is None:
                raise ValueError(f"Missing manifest for provider: '{state.provider_id}'")

            # Pop flow to enforce single-use authorization code exchange
            self._active_flows.pop(flow_id, None)

            return {
                "token_endpoint": manifest.token_endpoint,
                "client_id": manifest.client_id,
                "grant_type": "authorization_code",
                "code": auth_code,
                "code_verifier": state.code_verifier,
                "provider_id": state.provider_id,
            }
