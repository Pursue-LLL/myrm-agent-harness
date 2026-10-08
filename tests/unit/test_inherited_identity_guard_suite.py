"""Unit tests for Inherited Identity Guard in Harness.

Verifies environment sanitization, official source validation,
resume argument safety, and session plan derivation.
"""

from myrm_agent_harness.core.security.inherited_identity_guard import (
    AgentResumePlan,
    AgentSessionRef,
    AgentSessionRefKind,
    InheritedIdentitySanitizer,
    PersistedAgentSession,
    SanitizationPolicy,
    SanitizationResult,
    is_official_agent_source,
    is_valid_session_id,
    is_valid_session_path,
    normalize_session_start_source,
    validate_resume_argv,
)


def test_env_sanitization_default_stripped() -> None:
    sanitizer = InheritedIdentitySanitizer()
    dirty_env: dict[str, str] = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/user",
        "CODEX_THREAD_ID": "th-12345",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "sess-abcde",
        "MYRM_SESSION_ID": "myrm-sess-999",
        "MYRM_PANE_ID": "pane-1",
        "HERDR_SOCKET_PATH": "/tmp/herdr.sock",
        "CUSTOM_APP_VAR": "keep-me",
    }

    result: SanitizationResult = sanitizer.sanitize_env(dirty_env)

    assert result.is_isolated is True
    assert "CODEX_THREAD_ID" not in result.sanitized_env
    assert "CLAUDECODE" not in result.sanitized_env
    assert "CLAUDE_CODE_SESSION_ID" not in result.sanitized_env
    assert "MYRM_SESSION_ID" not in result.sanitized_env
    assert "MYRM_PANE_ID" not in result.sanitized_env
    assert "HERDR_SOCKET_PATH" not in result.sanitized_env
    assert result.sanitized_env["PATH"] == "/usr/bin:/bin"
    assert result.sanitized_env["HOME"] == "/home/user"
    assert result.sanitized_env["CUSTOM_APP_VAR"] == "keep-me"
    assert result.purged_count == 6


def test_env_sanitization_with_extra_override() -> None:
    sanitizer = InheritedIdentitySanitizer()
    dirty_env: dict[str, str] = {
        "MYRM_SESSION_ID": "old-parent-session",
        "USER": "alice",
    }
    extra_env: dict[str, str] = {
        "MYRM_SESSION_ID": "intentional-new-child-session",
        "NEW_VAR": "val",
    }

    result: SanitizationResult = sanitizer.sanitize_env(dirty_env, extra=extra_env)

    assert result.sanitized_env["USER"] == "alice"
    assert result.sanitized_env["MYRM_SESSION_ID"] == "intentional-new-child-session"
    assert result.sanitized_env["NEW_VAR"] == "val"


def test_env_sanitization_policy_options() -> None:
    policy = SanitizationPolicy(
        denied_env_keys=frozenset({"FORBIDDEN_VAR"}),
        allow_system_only=True,
    )
    sanitizer = InheritedIdentitySanitizer(default_policy=policy)
    env: dict[str, str] = {
        "PATH": "/bin",
        "HOME": "/home/user",
        "FORBIDDEN_VAR": "bad",
        "NON_SYSTEM_CUSTOM": "discarded",
    }

    result: SanitizationResult = sanitizer.sanitize_env(env)

    assert "PATH" in result.sanitized_env
    assert "HOME" in result.sanitized_env
    assert "FORBIDDEN_VAR" not in result.sanitized_env
    assert "NON_SYSTEM_CUSTOM" not in result.sanitized_env


def test_official_agent_sources() -> None:
    assert is_official_agent_source("myrm:claude", "claude") is True
    assert is_official_agent_source("myrm:codex", "codex") is True
    assert is_official_agent_source("herdr:pi", "pi") is True
    assert is_official_agent_source("herdr:antigravity_cli", "agy") is True

    # Untrusted or mismatched sources
    assert is_official_agent_source("untrusted:claude", "claude") is False
    assert is_official_agent_source("myrm:claude", "codex") is False
    assert is_official_agent_source("random_source", "unknown") is False


def test_normalize_session_start_source() -> None:
    assert normalize_session_start_source("startup") == "startup"
    assert normalize_session_start_source("RESUME ") == "resume"
    assert normalize_session_start_source("clear") == "clear"
    assert normalize_session_start_source("fork") == "fork"
    assert normalize_session_start_source("invalid_source") is None
    assert normalize_session_start_source(None) is None


def test_session_id_and_path_validation() -> None:
    assert is_valid_session_id("valid-session-id-123") is True
    assert is_valid_session_id("") is False
    assert is_valid_session_id("id\nwith_newline") is False
    assert is_valid_session_id("a" * 513) is False

    assert is_valid_session_path("/absolute/path/to/session.json") is True
    assert is_valid_session_path("relative/path/session.json") is False
    assert is_valid_session_path("") is False
    assert is_valid_session_path("/path\x00with/null") is False


def test_validate_resume_argv() -> None:
    valid_ok, valid_err = validate_resume_argv(["claude", "--resume", "sess-123"])
    assert valid_ok is True
    assert valid_err is None

    empty_ok, empty_err = validate_resume_argv([])
    assert empty_ok is False
    assert "empty" in str(empty_err)

    path_cmd_ok, path_cmd_err = validate_resume_argv(["/bin/sh", "--resume"])
    assert path_cmd_ok is False
    assert "plain command name" in str(path_cmd_err)

    ctrl_ok, ctrl_err = validate_resume_argv(["claude", "bad\narg"])
    assert ctrl_ok is False
    assert "control characters" in str(ctrl_err)

    quote_ok, quote_err = validate_resume_argv(["claude", "can't"])
    assert quote_ok is False
    assert "apostrophes" in str(quote_err)


def test_resolve_and_resume_plan() -> None:
    sanitizer = InheritedIdentitySanitizer()

    ref: AgentSessionRef | None = sanitizer.resolve_session_ref(
        source="myrm:claude",
        agent="claude",
        session_id="session-xyz-123",
    )
    assert ref is not None
    assert ref.kind == AgentSessionRefKind.ID
    assert ref.value == "session-xyz-123"

    persisted: PersistedAgentSession | None = sanitizer.build_persisted_session(
        source="myrm:claude",
        agent="claude",
        session_ref=ref,
    )
    assert persisted is not None
    assert persisted.agent == "claude"

    plan: AgentResumePlan | None = sanitizer.create_resume_plan(
        source="myrm:claude",
        agent="claude",
        session_ref=ref,
    )
    assert plan is not None
    assert plan.agent == "claude"
    assert plan.argv == ["claude", "--resume", "session-xyz-123"]
    assert "myrm:claude" in plan.dedupe_key

    # Rejection of unofficial source
    bad_plan = sanitizer.create_resume_plan(
        source="untrusted:source",
        agent="claude",
        session_ref=ref,
    )
    assert bad_plan is None
