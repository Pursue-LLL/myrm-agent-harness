"""RFC 7636 PKCE (Proof Key for Code Exchange) generation and verification engine.

[INPUT]
- State strings, client identifiers, redirect URIs, and scopes.

[OUTPUT]
- OAuthPkceChallenge and authorization URLs for desktop browser flow.

[POS]
- Harness core security engine securing desktop OAuth flows against interception.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse

from myrm_agent_harness.core.security.desktop_oauth_device.types import (
    OAuthPkceChallenge,
)


def _base64url_encode(data: bytes) -> str:
    """Encode bytes using URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_code_verifier(length: int = 64) -> str:
    """Generate high-entropy cryptographically random PKCE code verifier."""
    if length < 43 or length > 128:
        raise ValueError("PKCE code verifier length must be between 43 and 128 characters.")
    # secrets.token_urlsafe produces URL-safe characters
    token = secrets.token_urlsafe(length)
    return token[:length]


def compute_code_challenge(verifier: str) -> str:
    """Compute S256 code challenge from code verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _base64url_encode(digest)


def generate_pkce_challenge(state: str | None = None) -> OAuthPkceChallenge:
    """Generate complete PKCE challenge with verifier, challenge, and state."""
    verifier = generate_code_verifier()
    challenge = compute_code_challenge(verifier)
    assigned_state = state or secrets.token_hex(16)
    return OAuthPkceChallenge(
        code_verifier=verifier,
        code_challenge=challenge,
        code_challenge_method="S256",
        state=assigned_state,
    )


def verify_code_challenge(verifier: str, challenge: str) -> bool:
    """Verify that a code verifier matches the expected code challenge."""
    expected = compute_code_challenge(verifier)
    return secrets.compare_digest(expected, challenge)


def build_authorization_url(
    base_auth_url: str,
    client_id: str,
    redirect_uri: str,
    challenge: OAuthPkceChallenge,
    scopes: list[str] | None = None,
) -> str:
    """Build standard OAuth 2.0 authorization URL with PKCE parameters."""
    query_params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": challenge.state,
        "code_challenge": challenge.code_challenge,
        "code_challenge_method": challenge.code_challenge_method,
    }
    if scopes:
        query_params["scope"] = " ".join(scopes)

    encoded_params = urllib.parse.urlencode(query_params)
    delimiter = "&" if "?" in base_auth_url else "?"
    return f"{base_auth_url}{delimiter}{encoded_params}"
