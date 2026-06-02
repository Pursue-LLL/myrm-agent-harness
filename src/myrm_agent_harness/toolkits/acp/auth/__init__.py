"""Subscription authentication subsystem for external CLI agent backends.

Lets a delegated CLI (Codex / Claude Code / Gemini / Qwen …) run on the user's own
model subscription instead of a metered API key. Provides three framework-level
mechanisms, all GUI/SaaS-driven by the business layer:

- credential detection — is this backend logged in? (pre-flight checks, status badges)
- interactive login — drive ``<cli> login`` and stream URLs/codes to the user
- credential import — the universal fallback: persist a credential captured elsewhere

[OUTPUT]
- LoginStrategy, AuthProfile, profile_for, known_backends
- AuthStatus, CredentialState, CredentialStore
- AuthEventType, AuthEvent, CliLoginSession

[POS]
Public surface of the ACP auth subsystem.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.acp.auth._profiles import (
    AuthProfile,
    LoginStrategy,
    known_backends,
    profile_for,
)
from myrm_agent_harness.toolkits.acp.auth.credential_store import (
    AuthStatus,
    CredentialState,
    CredentialStore,
)
from myrm_agent_harness.toolkits.acp.auth.login_session import (
    AuthEvent,
    AuthEventType,
    CliLoginSession,
)

__all__ = [
    "AuthEvent",
    "AuthEventType",
    "AuthProfile",
    "AuthStatus",
    "CliLoginSession",
    "CredentialState",
    "CredentialStore",
    "LoginStrategy",
    "known_backends",
    "profile_for",
]
