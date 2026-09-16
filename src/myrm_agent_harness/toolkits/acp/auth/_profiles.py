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
- cli_launch_args: Baseline non-interactive launch args for a backend.
- resolve_cli_args: Merge launch args with config args and permission-mode args.

[POS]
Authentication profile registry for the ACP auth subsystem. Sole owner of per-CLI
launch and permission arguments, so no business-layer caller hard-codes CLI flags.
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
    non_interactive_flags: tuple[str, ...] = ()  # CLI flags granting full autonomy, applied only in allow_all/bypass
    cli_launch_args: tuple[str, ...] = ()  # baseline non-interactive invocation args (no prompt, no permission flags)

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
        non_interactive_flags=("--dangerously-bypass-approvals-and-sandbox",),
        cli_launch_args=("exec", "--json", "-s", "read-only"),
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
        non_interactive_flags=("--dangerously-skip-permissions",),
        cli_launch_args=("-p", "--output-format", "stream-json", "--verbose"),
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
        non_interactive_flags=("--approval-mode=yolo",),
        cli_launch_args=("--output-format", "stream-json", "--approval-mode=plan"),
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
        non_interactive_flags=("--approval-mode=yolo",),
        cli_launch_args=("--output-format", "stream-json", "--approval-mode=plan"),
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


def cli_launch_args(backend_or_command: str) -> list[str]:
    """Baseline non-interactive launch args for a CLI backend, or an empty list.

    Business layers call this instead of hard-coding per-CLI arguments, so all CLI
    invocation knowledge stays in this registry and cannot drift across layers.
    """
    profile = profile_for(backend_or_command)
    return list(profile.cli_launch_args) if profile else []


# Permission-mode args per backend. Index 0 is the flag name, the remainder is its
# value; both are emitted as separate argv entries so `--flag=value` and `--flag value`
# conventions are avoided on CLIs whose parsers only accept spaced values.
_PERMISSION_MODE_ARGS: dict[str, dict[str, tuple[str, ...]]] = {
    "claude": {
        "safe": ("--permission-mode", "dontAsk"),
        "ask": ("--permission-mode", "acceptEdits"),
        "allow_all": ("--permission-mode", "acceptEdits"),
    },
    "codex": {
        "safe": ("-s", "read-only"),
        "ask": ("-s", "workspace-write"),
        "allow_all": ("-s", "workspace-write"),
    },
    "gemini": {
        "safe": ("--approval-mode", "plan"),
        "ask": ("--approval-mode", "auto_edit"),
        "allow_all": ("--approval-mode", "yolo"),
    },
    "qwen": {
        # qwen-code is a gemini-cli fork but exposes different mode names; its exact
        # contract is not verifiable in-repo, so every mode pins read-only rather than
        # guessing a permissive value.
        "safe": ("--approval-mode", "plan"),
        "ask": ("--approval-mode", "plan"),
        "allow_all": ("--approval-mode", "plan"),
    },
}

# Flags a permission mapping owns; stripped from configured args first so the mapping
# stays the single owner and avoids clap-level duplicate/conflict errors (codex's
# -s / --approve-for-me / --dangerously-bypass-* are mutually exclusive).
_PERMISSION_FLAGS: frozenset[str] = frozenset(
    {
        "-y",
        "--yolo",
        "-s",
        "--sandbox",
        "--full-auto",
        "--approve-for-me",
        "--dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--permission-mode",
        "--approval-mode",
    }
)

# Flags whose value is a separate argv entry and must be dropped together with them.
_PERMISSION_VALUE_FLAGS: frozenset[str] = frozenset({"-s", "--sandbox", "--permission-mode", "--approval-mode"})


def resolve_cli_args(
    backend_or_command: str,
    configured_args: list[str],
    permission_mode: str,
) -> list[str]:
    """Merge baseline launch args with config args and the permission-mode args.

    Deterministic order: permission args, then baseline args, then configured args
    minus anything the permission mapping owns. The mapping is the sole owner of the
    permission flags, so a config carrying an explicit (often stale) flag can never
    contradict the mode the user selected.
    """
    profile = profile_for(backend_or_command)
    if profile is None:
        # Unknown CLI: we own no permission contract for it, so args pass through
        # untouched rather than stripping flags that may mean something else entirely.
        return list(configured_args)

    merged: list[str] = []
    mode_args = _PERMISSION_MODE_ARGS.get(profile.backend, {}).get(permission_mode, ())
    if permission_mode == "bypass":
        mode_args = profile.non_interactive_flags
    merged.extend(mode_args)
    merged.extend(profile.cli_launch_args)
    merged.extend(_strip_permission_flags(configured_args))
    return _dedupe_preserving_order(merged)


def _strip_permission_flags(args: list[str]) -> list[str]:
    """Drop permission flags (and their spaced values) from configured args."""
    kept: list[str] = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        if arg in _PERMISSION_FLAGS:
            skip_value = arg in _PERMISSION_VALUE_FLAGS
            continue
        kept.append(arg)
    return kept


def _dedupe_preserving_order(args: list[str]) -> list[str]:
    """Remove exact duplicates without disturbing the resolved ordering."""
    seen: set[str] = set()
    unique: list[str] = []
    for arg in args:
        if arg in seen:
            continue
        seen.add(arg)
        unique.append(arg)
    return unique
