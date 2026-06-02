"""Tests for the ACP subscription auth subsystem.

Covers auth profiles, credential detection/import/clear, the interactive login
session driver, and auth_mode-aware environment sanitization.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from myrm_agent_harness.toolkits.acp.auth import (
    AuthEventType,
    AuthProfile,
    AuthStatus,
    CliLoginSession,
    CredentialStore,
    LoginStrategy,
    known_backends,
    profile_for,
)
from myrm_agent_harness.toolkits.acp.runtime._base import build_safe_env
from myrm_agent_harness.toolkits.acp.types import RuntimeConfig

_POSIX = os.name == "posix"


class TestProfiles:
    def test_known_backends(self) -> None:
        assert set(known_backends()) == {"codex", "claude", "gemini", "qwen"}

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("codex", "codex"),
            ("codex-cli", "codex"),
            ("claude-code", "claude"),
            ("/usr/local/bin/codex", "codex"),
            ("gemini.cmd", "gemini"),
            ("qwen", "qwen"),
        ],
    )
    def test_profile_for_resolves(self, token: str, expected: str) -> None:
        profile = profile_for(token)
        assert profile is not None
        assert profile.backend == expected

    def test_profile_for_unknown(self) -> None:
        assert profile_for("totally-unknown-agent") is None
        assert profile_for("") is None

    def test_scriptable_login(self) -> None:
        assert profile_for("codex").scriptable_login is True  # type: ignore[union-attr]
        assert profile_for("gemini").scriptable_login is False  # type: ignore[union-attr]

    def test_resolve_home_default(self) -> None:
        profile = profile_for("codex")
        assert profile is not None
        home = profile.resolve_home({"HOME": "/home/u"})
        assert str(home) == "/home/u/.codex"

    def test_resolve_home_env_override(self) -> None:
        profile = profile_for("codex")
        assert profile is not None
        home = profile.resolve_home({"HOME": "/home/u", "CODEX_HOME": "/persistent/.codex"})
        assert str(home) == "/persistent/.codex"


class TestCredentialStore:
    def test_state_not_authenticated(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        state = store.state("codex")
        assert state.status is AuthStatus.NOT_AUTHENTICATED
        assert state.authenticated is False

    def test_state_unknown_backend(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        assert store.state("mystery").status is AuthStatus.UNKNOWN

    def test_import_then_authenticated(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        state = store.import_credential("codex", '{"tokens": {"access_token": "abc"}}')
        assert state.status is AuthStatus.AUTHENTICATED
        assert store.is_authenticated("codex") is True
        written = tmp_path / ".codex" / "auth.json"
        assert written.is_file()
        assert json.loads(written.read_text())["tokens"]["access_token"] == "abc"

    @pytest.mark.skipif(not _POSIX, reason="POSIX file permissions")
    def test_import_sets_owner_only_perms(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        store.import_credential("codex", '{"x": 1}')
        mode = (tmp_path / ".codex" / "auth.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_import_env_override_home(self, tmp_path) -> None:
        persistent = tmp_path / "persistent" / ".codex"
        store = CredentialStore({"HOME": str(tmp_path), "CODEX_HOME": str(persistent)})
        store.import_credential("codex", '{"x": 1}')
        assert (persistent / "auth.json").is_file()

    def test_import_claude_credentials_file(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        store.import_credential("claude", '{"claudeAiOauth": {"accessToken": "t"}}')
        assert (tmp_path / ".claude" / ".credentials.json").is_file()

    def test_import_empty_raises(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        with pytest.raises(ValueError, match="empty"):
            store.import_credential("codex", "   ")

    def test_import_invalid_json_raises(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        with pytest.raises(ValueError, match="not valid JSON"):
            store.import_credential("codex", "not json")

    def test_import_unknown_backend_raises(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        with pytest.raises(ValueError, match="No auth profile"):
            store.import_credential("mystery", '{"x": 1}')

    @pytest.mark.parametrize("bad", ["../escape.json", "sub/dir.json", ".."])
    def test_import_bad_filename_raises(self, tmp_path, bad: str) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        with pytest.raises(ValueError, match="Invalid credential filename"):
            store.import_credential("codex", '{"x": 1}', filename=bad)

    def test_import_empty_filename_uses_default(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        store.import_credential("codex", '{"x": 1}', filename="")
        assert (tmp_path / ".codex" / "auth.json").is_file()

    def test_clear_removes_credentials(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        store.import_credential("codex", '{"x": 1}')
        assert store.is_authenticated("codex") is True
        state = store.clear("codex")
        assert state.status is AuthStatus.NOT_AUTHENTICATED
        assert store.is_authenticated("codex") is False

    def test_clear_idempotent(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        assert store.clear("codex").status is AuthStatus.NOT_AUTHENTICATED

    def test_empty_credential_file_not_authenticated(self, tmp_path) -> None:
        cred = tmp_path / ".codex" / "auth.json"
        cred.parent.mkdir(parents=True)
        cred.write_text("")
        store = CredentialStore({"HOME": str(tmp_path)})
        assert store.is_authenticated("codex") is False


class TestBuildSafeEnvAuthMode:
    def test_subscription_strips_all_provider_secrets(self) -> None:
        cfg = RuntimeConfig(backend_type="cli", command="codex", auth_mode="subscription")
        env = build_safe_env(
            cfg,
            base_env={
                "OPENAI_API_KEY": "o",
                "GEMINI_API_KEY": "g",
                "XAI_API_KEY": "x",
                "QWEN_API_KEY": "q",
                "MISTRAL_API_KEY": "m",
                "PATH": "/bin",
                "HOME": "/h",
            },
        )
        for secret in ("OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "QWEN_API_KEY", "MISTRAL_API_KEY"):
            assert secret not in env
        assert env["PATH"] == "/bin"
        assert env["HOME"] == "/h"

    def test_subscription_drops_injected_secret_keeps_plain(self) -> None:
        cfg = RuntimeConfig(
            backend_type="cli",
            command="codex",
            auth_mode="subscription",
            env={"OPENAI_API_KEY": "injected", "NODE_OPTIONS": "--max-old-space-size=4096"},
        )
        env = build_safe_env(cfg, base_env={"PATH": "/bin"})
        assert "OPENAI_API_KEY" not in env
        assert env["NODE_OPTIONS"] == "--max-old-space-size=4096"

    def test_api_key_injects_provider_secret(self) -> None:
        cfg = RuntimeConfig(
            backend_type="cli",
            command="codex",
            auth_mode="api_key",
            env={"OPENAI_API_KEY": "injected"},
        )
        env = build_safe_env(cfg, base_env={"OPENAI_API_KEY": "from-host", "PATH": "/bin"})
        assert env["OPENAI_API_KEY"] == "injected"

    def test_strip_env_keys_honoured(self) -> None:
        cfg = RuntimeConfig(backend_type="cli", command="codex", strip_env_keys=["MY_TOKEN"])
        env = build_safe_env(cfg, base_env={"MY_TOKEN": "secret", "PATH": "/bin"})
        assert "MY_TOKEN" not in env


_LOGIN_OK_SCRIPT = (
    "import os, pathlib;"
    "print('To sign in, visit https://auth.example.com/device and enter ABCD-1234');"
    "p = pathlib.Path(os.environ['CODEX_HOME']) / 'auth.json';"
    "p.parent.mkdir(parents=True, exist_ok=True);"
    "p.write_text('{\"ok\": true}')"
)

_LOGIN_FAIL_SCRIPT = "import sys; sys.stderr.write('login failed\\n'); sys.exit(3)"


def _codex_login_profile(login_args: tuple[str, ...]) -> AuthProfile:
    return AuthProfile(
        backend="codex",
        home_env="CODEX_HOME",
        home_dir=".codex",
        credential_files=("auth.json",),
        login_strategy=LoginStrategy.DEVICE_CODE,
        login_args=login_args,
        logout_args=None,
        needs_code_input=False,
        api_key_env=("OPENAI_API_KEY",),
    )


class TestCliLoginSession:
    @pytest.mark.asyncio
    async def test_non_scriptable_yields_import_prompt(self) -> None:
        profile = profile_for("gemini")
        assert profile is not None
        session = CliLoginSession("gemini", profile)
        events = [e async for e in session.run()]
        assert len(events) == 1
        assert events[0].type is AuthEventType.PROMPT
        assert "import" in events[0].message.lower()

    @pytest.mark.asyncio
    async def test_successful_login_persists_and_succeeds(self, tmp_path) -> None:
        codex_home = tmp_path / ".codex"
        profile = _codex_login_profile(("-c", _LOGIN_OK_SCRIPT))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(codex_home)},
        )
        events = [e async for e in session.run()]
        types = [e.type for e in events]
        assert AuthEventType.SUCCESS in types

        prompts = [e for e in events if e.type is AuthEventType.PROMPT]
        assert any(e.url == "https://auth.example.com/device" for e in prompts)
        assert any(e.code == "ABCD-1234" for e in prompts)
        assert (codex_home / "auth.json").is_file()

    @pytest.mark.asyncio
    async def test_failed_login_emits_error(self, tmp_path) -> None:
        profile = _codex_login_profile(("-c", _LOGIN_FAIL_SCRIPT))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        events = [e async for e in session.run()]
        assert events[-1].type is AuthEventType.ERROR

    @pytest.mark.asyncio
    async def test_missing_executable_emits_error(self, tmp_path) -> None:
        profile = _codex_login_profile(("login",))
        session = CliLoginSession(
            "/nonexistent/codex-binary-xyz",
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        events = [e async for e in session.run()]
        assert any(e.type is AuthEventType.ERROR for e in events)
