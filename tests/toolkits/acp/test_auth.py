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

    def test_permission_tables_cover_every_profile(self) -> None:
        """A profile added without permission tables must fail, not mis-resolve args."""
        from myrm_agent_harness.toolkits.acp.auth._profiles import _permission_backends

        assert set(_permission_backends()) == set(known_backends())

    def test_permission_table_drift_is_rejected_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A half-configured backend must raise with diagnostics instead of mis-resolving."""
        from myrm_agent_harness.toolkits.acp.auth import _profiles

        monkeypatch.delitem(_profiles._PERMISSION_FLAGS_BY_BACKEND, "qwen")
        with pytest.raises(ValueError, match="out of sync with _PROFILES"):
            _profiles._permission_backends()

    def test_resolve_rejects_a_half_configured_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """resolve_cli_args must fail loudly, never merge against missing permissions."""
        from myrm_agent_harness.toolkits.acp.auth import _profiles

        monkeypatch.setattr(
            _profiles,
            "_PERMISSION_MODE_ARGS",
            {k: v for k, v in _profiles._PERMISSION_MODE_ARGS.items() if k != "qwen"},
        )
        with pytest.raises(ValueError, match="out of sync with _PROFILES"):
            _profiles.resolve_cli_args("qwen", ["--output-format", "stream-json"], "safe")

    def test_cli_launch_args_unknown_backend_is_empty(self) -> None:
        from myrm_agent_harness.toolkits.acp.auth._profiles import cli_launch_args

        assert cli_launch_args("no-such-cli") == []
        assert cli_launch_args("codex") == ["exec", "--json"]

    @pytest.mark.parametrize("backend", ["codex", "claude", "gemini", "qwen"])
    @pytest.mark.parametrize("mode", ["safe", "ask", "allow_all", "bypass"])
    def test_every_backend_and_mode_resolves_arguments(self, backend: str, mode: str) -> None:
        from myrm_agent_harness.toolkits.acp.auth._profiles import resolve_cli_args

        resolved = resolve_cli_args(backend, [], mode)
        assert resolved, f"{backend}/{mode} resolved to no arguments"

    def test_mode_owned_flags_replace_stale_config_flags(self) -> None:
        """Stored configs carrying an old permission flag must not override the mode."""
        from myrm_agent_harness.toolkits.acp.auth._profiles import resolve_cli_args

        # codex's `--yolo` is an alias of the bypass flag and conflicts with --sandbox.
        assert "--yolo" not in resolve_cli_args("codex", ["--yolo"], "safe")
        # A stored bypass flag must be replaced by the selected mode's own sandbox choice.
        stale_bypass = resolve_cli_args("codex", ["--dangerously-bypass-approvals-and-sandbox"], "safe")
        assert "--dangerously-bypass-approvals-and-sandbox" not in stale_bypass
        assert stale_bypass[stale_bypass.index("--sandbox") + 1] == "read-only"
        # The `--flag=value` spelling escapes a plain name lookup and must be stripped.
        gemini = resolve_cli_args("gemini", ["--approval-mode=plan"], "allow_all")
        assert gemini.count("--approval-mode") == 1
        assert gemini[gemini.index("--approval-mode") + 1] == "yolo"
        codex_eq = resolve_cli_args("codex", ["--sandbox=read-only"], "allow_all")
        assert codex_eq.count("--sandbox") == 1
        assert "--sandbox=read-only" not in codex_eq
        # Stripping is scoped per backend: gemini's own sandbox toggle survives in both
        # spellings, because that flag is the user's, not one this mapping owns.
        assert "-s" in resolve_cli_args("gemini", ["-s"], "safe")
        assert "--sandbox=true" in resolve_cli_args("gemini", ["--sandbox=true"], "safe")
        # A hook-trust switch has no substitute in the mapping, so it must not be dropped.
        assert "--dangerously-bypass-hook-trust" in resolve_cli_args(
            "codex", ["--dangerously-bypass-hook-trust"], "safe"
        )

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

    def test_import_oversized_credential_raises(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        oversized = '{"x": "' + "a" * (300 * 1024) + '"}'
        with pytest.raises(ValueError, match="exceeds"):
            store.import_credential("codex", oversized)

    def test_clear_unknown_backend_raises(self, tmp_path) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        with pytest.raises(ValueError, match="No auth profile"):
            store.clear("mystery")

    def test_clear_survives_unlink_oserror(self, tmp_path, monkeypatch) -> None:
        store = CredentialStore({"HOME": str(tmp_path)})
        store.import_credential("codex", '{"x": 1}')

        real_unlink = tmp_path.__class__.unlink

        def _flaky_unlink(self, *args, **kwargs):
            if self.name.endswith("auth.json"):
                raise OSError("permission denied")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(tmp_path.__class__, "unlink", _flaky_unlink)

        state = store.clear("codex")
        assert state.status is AuthStatus.NOT_AUTHENTICATED


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

    @pytest.mark.asyncio
    async def test_login_timeout_emits_error(self, tmp_path) -> None:
        # Never exits: forces the asyncio.timeout path (L139-142).
        sleepy = "import time; time.sleep(60)"
        profile = _codex_login_profile(("-c", sleepy))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
            timeout_seconds=1,
        )
        events = [e async for e in session.run()]
        assert events[-1].type is AuthEventType.ERROR
        assert "timed out" in events[-1].message

    @pytest.mark.asyncio
    async def test_finished_without_credential_emits_error(self, tmp_path) -> None:
        # Exits 0 but never writes a credential file (L150-153).
        noop = "pass"
        profile = _codex_login_profile(("-c", noop))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        events = [e async for e in session.run()]
        assert events[-1].type is AuthEventType.ERROR
        assert "no credential was persisted" in events[-1].message

    @pytest.mark.asyncio
    async def test_feed_forwards_line_to_stdin(self, tmp_path) -> None:
        # Reads one stdin line and prints it back; exercises feed() (L157-166).
        echo_stdin = (
            "import sys, os, pathlib;"
            "line = sys.stdin.readline();"
            "print('received:' + line.strip());"
            "p = pathlib.Path(os.environ['CODEX_HOME']) / 'auth.json';"
            "p.parent.mkdir(parents=True, exist_ok=True);"
            "p.write_text('{\"ok\": true}')"
        )
        profile = _codex_login_profile(("-c", echo_stdin))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        iterator = session.run()
        first = await anext(iterator)  # STATUS: process spawned, stdin open
        assert first.type is AuthEventType.STATUS
        # The child blocks on stdin.readline(); unblock it by feeding a line now.
        await session.feed("ABCD-EFGH")
        rest = [e async for e in iterator]
        events = [first, *rest]
        assert any(e.type is AuthEventType.SUCCESS for e in events)
        assert any("received:ABCD-EFGH" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_feed_after_process_exit_is_noop(self, tmp_path) -> None:
        profile = _codex_login_profile(("-c", "pass"))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        _ = [e async for e in session.run()]
        # Process is gone: feed must not raise (guarded by proc is None / closing stdin).
        await session.feed("ABCD-EFGH")

    @pytest.mark.asyncio
    async def test_cancel_terminates_process_group(self, tmp_path) -> None:
        profile = _codex_login_profile(("-c", "import time; time.sleep(60)"))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        iterator = session.run()
        await anext(iterator)  # STATUS event: process spawned
        await session.cancel()
        # cancel() is idempotent and safe after termination.
        await session.cancel()

    @pytest.mark.asyncio
    async def test_classify_skips_blank_line(self, tmp_path) -> None:
        # A blank console line must not surface as an event (L175-176).
        blank_line = (
            "import sys, os, pathlib;"
            "print('');"
            "p = pathlib.Path(os.environ['CODEX_HOME']) / 'auth.json';"
            "p.parent.mkdir(parents=True, exist_ok=True);"
            "p.write_text('{\"ok\": true}')"
        )
        profile = _codex_login_profile(("-c", blank_line))
        session = CliLoginSession(
            sys.executable,
            profile,
            base_env={**os.environ, "CODEX_HOME": str(tmp_path / ".codex")},
        )
        events = [e async for e in session.run()]
        assert not any(e.message == "" for e in events)
