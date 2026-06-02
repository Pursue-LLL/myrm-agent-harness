"""Authentication profiles for known external CLI agent backends.

Captures, per backend, where its subscription login state lives, how to launch an
interactive login, and which provider keys map to api-key mode. Business and
control-plane layers read these to drive GUI login, status badges, and credential
persistence without hard-coding CLI specifics anywhere upstream.

[INPUT]
no — leaf module, standard library only

[OUTPUT]
- LoginStrategy: How a CLI performs interactive login.
- AuthProfile: Per-backend authentication characteristics.
- profile_for: Resolve an AuthProfile from a backend name or command.

[POS]
Authentication profile registry for the ACP auth subsystem.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class LoginStrategy(StrEnum):
    """How a CLI backend performs an interactive subscription login."""

    DEVICE_CODE = "device_code"  # CLI prints a URL/code; user authorizes in a browser, CLI polls
    BROWSER_OAUTH = "browser_oauth"  # CLI opens a browser and runs a local loopback callback
    SETUP_TOKEN = "setup_token"  # CLI prints a URL; user pastes the returned auth code back via stdin
    MANUAL_IMPORT = "manual_import"  # no scriptable login on this host; only credential import works


@dataclass(frozen=True, slots=True)
class AuthProfile:
    """Authentication characteristics of a known CLI agent backend.

    Paths are resolved against a supplied environment so the control plane can
    relocate a CLI's home (e.g. ``CODEX_HOME`` → ``/persistent/.codex``) without
    any change here.
    """

    backend: str
    home_env: str | None  # env var that overrides the CLI home dir, if the CLI honours one
    home_dir: str  # default home subdir under $HOME (e.g. ".codex")
    credential_files: tuple[str, ...]  # candidate credential filenames within the home dir
    login_strategy: LoginStrategy
    login_args: tuple[str, ...]  # args appended to the command to start login ("" → not scriptable)
    logout_args: tuple[str, ...] | None
    needs_code_input: bool  # whether login expects the user to paste a code back via stdin
    api_key_env: tuple[str, ...]  # provider key env names used in api_key mode

    def resolve_home(self, env: Mapping[str, str]) -> Path:
        """Resolve the CLI home directory, honouring an override env var if set."""
        if self.home_env:
            override = env.get(self.home_env)
            if override:
                return Path(override).expanduser()
        home = env.get("HOME") or os.path.expanduser("~")
        return Path(home) / self.home_dir

    def resolve_credential_paths(self, env: Mapping[str, str]) -> list[Path]:
        """Candidate credential file paths in priority order."""
        base = self.resolve_home(env)
        return [base / name for name in self.credential_files]

    @property
    def scriptable_login(self) -> bool:
        """Whether an interactive login can be driven by spawning the CLI."""
        return bool(self.login_args) and self.login_strategy is not LoginStrategy.MANUAL_IMPORT


# Per-backend profiles. Credential locations and home-override vars below reflect
# each CLI's documented behaviour; the manual-import fallback (credential_store)
# guarantees a working path even where scripted login is unavailable.
_PROFILES: dict[str, AuthProfile] = {
    "codex": AuthProfile(
        backend="codex",
        home_env="CODEX_HOME",
        home_dir=".codex",
        credential_files=("auth.json",),
        login_strategy=LoginStrategy.DEVICE_CODE,
        login_args=("login",),
        logout_args=("logout",),
        needs_code_input=False,
        api_key_env=("OPENAI_API_KEY",),
    ),
    "claude": AuthProfile(
        backend="claude",
        home_env="CLAUDE_CONFIG_DIR",
        home_dir=".claude",
        credential_files=(".credentials.json",),
        login_strategy=LoginStrategy.SETUP_TOKEN,
        login_args=("setup-token",),
        logout_args=None,
        needs_code_input=True,
        api_key_env=("ANTHROPIC_API_KEY",),
    ),
    "gemini": AuthProfile(
        backend="gemini",
        home_env=None,
        home_dir=".gemini",
        credential_files=("oauth_creds.json",),
        login_strategy=LoginStrategy.BROWSER_OAUTH,
        login_args=(),
        logout_args=None,
        needs_code_input=False,
        api_key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    ),
    "qwen": AuthProfile(
        backend="qwen",
        home_env=None,
        home_dir=".qwen",
        credential_files=("oauth_creds.json",),
        login_strategy=LoginStrategy.BROWSER_OAUTH,
        login_args=(),
        logout_args=None,
        needs_code_input=False,
        api_key_env=("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
    ),
}


def _normalize(token: str) -> str:
    """Reduce a command path or agent name to a bare lowercase backend key."""
    base = os.path.basename(token.strip()).lower()
    return base.split(".", 1)[0]  # drop extensions like .cmd / .exe


def profile_for(backend_or_command: str) -> AuthProfile | None:
    """Resolve an AuthProfile from a backend name or executable command.

    Matches the executable basename first (``/usr/bin/codex`` → ``codex``), then
    falls back to a substring scan so configured names like ``codex-cli`` or
    ``claude-code`` still resolve.
    """
    if not backend_or_command:
        return None
    key = _normalize(backend_or_command)
    direct = _PROFILES.get(key)
    if direct is not None:
        return direct
    for name, profile in _PROFILES.items():
        if name in key:
            return profile
    return None


def known_backends() -> tuple[str, ...]:
    """Names of all backends with a registered auth profile."""
    return tuple(_PROFILES)
