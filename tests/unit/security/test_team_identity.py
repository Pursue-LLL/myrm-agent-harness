"""Team-shared conversation identity scope — DTO and pure helper contracts."""

from myrm_agent_harness.agent.security import (
    CredentialTrack,
    TeamIdentityScope,
    TeamIdentitySpec,
    credential_track_for,
    memory_namespace_for,
    sanitize_identity_id,
)


def test_sanitize_identity_id_strips_unsafe_chars() -> None:
    assert sanitize_identity_id("Yi Fu!!") == "yifu"
    assert sanitize_identity_id("  ") == "baseline"
    assert sanitize_identity_id("a" * 100) == "a" * 64


def test_memory_namespace_for_prefixes_ident() -> None:
    assert memory_namespace_for("义父") == "ident:baseline"
    assert memory_namespace_for("helper-1") == "ident:helper-1"


def test_credential_track_group_shared_only() -> None:
    assert credential_track_for(is_group=True, scope=TeamIdentityScope.SHARED) == CredentialTrack.SHARED
    assert credential_track_for(is_group=False, scope=TeamIdentityScope.SHARED) == CredentialTrack.PERSONAL
    assert credential_track_for(is_group=True, scope=TeamIdentityScope.PERSONAL) == CredentialTrack.PERSONAL


def test_spec_normalizes_namespace_to_identity_id() -> None:
    spec = TeamIdentitySpec(
        scope=TeamIdentityScope.SHARED,
        identity_id="Helper 1!",
        credential_track=CredentialTrack.SHARED,
        memory_namespace="ident:stale",
    )
    assert spec.identity_id == "helper1"
    assert spec.memory_namespace == "ident:helper1"


def test_spec_defaults_are_personal_fallback() -> None:
    spec = TeamIdentitySpec()
    assert spec.scope == TeamIdentityScope.PERSONAL
    assert spec.credential_track == CredentialTrack.PERSONAL
    assert spec.is_fallback is True
