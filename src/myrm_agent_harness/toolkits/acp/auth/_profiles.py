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
    cli_launch_args: tuple[str, ...] = ()  # baseline non-interactive invocation args (never permission flags)

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
        cli_launch_args=("exec", "--json"),
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
        cli_launch_args=("--output-format", "stream-json"),
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
        cli_launch_args=("--output-format", "stream-json"),
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
#
# Every value below is taken from the CLI's own documentation:
# - claude: `--permission-mode` accepts default / acceptEdits / plan / auto / dontAsk /
#   bypassPermissions. `acceptEdits` is the non-interactive step that approves edit-class
#   operations, so it is the closest CLI-side match for "approve each step".
# - codex: the `exec` entry point already hardcodes approval-policy `never` (headless
#   never prompts) and does not accept `--ask-for-approval`, so `-s/--sandbox` is the
#   only lever. `--dangerously-bypass-approvals-and-sandbox` is the sandbox escape hatch
#   (it implies full access) and therefore replaces the selector instead of joining it.
# - gemini: `--approval-mode` validates the value with yargs against default / auto_edit /
#   yolo / plan, where plan is read-only.
# - qwen: forked from gemini but validates plan / default / auto-edit / yolo, so the edit
#   mode is spelled with a hyphen here rather than gemini's underscore.
_PERMISSION_MODE_ARGS: dict[str, dict[str, tuple[str, ...]]] = {
    "claude": {
        "safe": ("--permission-mode", "default"),
        "ask": ("--permission-mode", "acceptEdits"),
        "allow_all": ("--permission-mode", "bypassPermissions"),
        "bypass": ("--permission-mode", "bypassPermissions"),
    },
    "codex": {
        "safe": ("--sandbox", "read-only"),
        "ask": ("--sandbox", "workspace-write"),
        "allow_all": ("--sandbox", "workspace-write"),
        "bypass": ("--dangerously-bypass-approvals-and-sandbox",),
    },
    "gemini": {
        "safe": ("--approval-mode", "plan"),
        "ask": ("--approval-mode", "auto_edit"),
        "allow_all": ("--approval-mode", "yolo"),
        "bypass": ("--approval-mode", "yolo"),
    },
    "qwen": {
        "safe": ("--approval-mode", "plan"),
        "ask": ("--approval-mode", "auto-edit"),
        "allow_all": ("--approval-mode", "yolo"),
        "bypass": ("--approval-mode", "yolo"),
    },
}

# Permission flags a mapping owns, keyed by backend. Stripping is deliberately
# per-backend: `-s` is codex's sandbox *mode* (`-s read-only`) but gemini's boolean
# sandbox *toggle*, so a global strip would silently disable sandboxing the user asked
# for. Each entry holds the exact flag names, the names whose value is a separate argv
# element, and the per-backend `--flag=value` prefixes — gemini's `--sandbox=true` is the
# user's own toggle and must survive, while codex's `--sandbox=read-only` is the mode this
# mapping owns.
_PERMISSION_FLAGS_BY_BACKEND: dict[str, tuple[frozenset[str], frozenset[str], tuple[str, ...]]] = {
    "claude": (
        frozenset({"--permission-mode", "--dangerously-skip-permissions", "--full-auto"}),
        frozenset({"--permission-mode"}),
        ("--permission-mode=",),
    ),
    "codex": (
        # Only flags this mapping replaces belong here. Hook trust is a separate concern
        # the mapping has no substitute for, so `--dangerously-bypass-hook-trust` is left
        # alone rather than silently dropped.
        frozenset(
            {
                "-s",
                "--sandbox",
                "--full-auto",
                "--approve-for-me",
                "--yolo",
                "--dangerously-bypass-approvals-and-sandbox",
            }
        ),
        frozenset({"-s", "--sandbox"}),
        ("--sandbox=",),
    ),
    "gemini": (
        frozenset({"-y", "--yolo", "--approval-mode"}),
        frozenset({"--approval-mode"}),
        ("--approval-mode=",),
    ),
    "qwen": (
        frozenset({"-y", "--yolo", "--approval-mode"}),
        frozenset({"--approval-mode"}),
        ("--approval-mode=",),
    ),
}


def _permission_backends() -> frozenset[str]:
    """Backends that have both a permission mapping and a strip table.

    The two tables must cover exactly the same backends: a mode mapping without a
    strip table would resolve to a duplicated flag (a parser error or a silent
    last-wins override), and a strip table without a mapping would leave the user in
    an unspecified mode. Evaluated on each resolve so a half-added backend fails loudly
    at first invocation instead of silently mis-resolving arguments.
    """
    backends = frozenset(_PERMISSION_MODE_ARGS) & frozenset(_PERMISSION_FLAGS_BY_BACKEND)
    if backends != frozenset(profile.backend for profile in _PROFILES.values()):
        msg = (
            "Permission tables are out of sync with _PROFILES: "
            f"profiles={sorted(p.backend for p in _PROFILES.values())}, "
            f"mode_args={sorted(_PERMISSION_MODE_ARGS)}, "
            f"strip_flags={sorted(_PERMISSION_FLAGS_BY_BACKEND)}"
        )
        raise ValueError(msg)
    return backends


def _strip_permission_flags(backend: str, args: list[str]) -> list[str]:
    """Drop the permission flags this backend's mapping owns, plus their values."""
    flag_lookup, value_flags, prefix_flags = _PERMISSION_FLAGS_BY_BACKEND[backend]
    kept: list[str] = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        if arg in flag_lookup or arg.startswith(prefix_flags):
            skip_value = arg in value_flags
            continue
        kept.append(arg)
    return kept


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
    if profile.backend not in _permission_backends():
        # A profile registered without permission tables has no defined contract here.
        return list(configured_args)

    merged: list[str] = []
    merged.extend(_PERMISSION_MODE_ARGS[profile.backend].get(permission_mode, ()))
    merged.extend(profile.cli_launch_args)
    merged.extend(_strip_permission_flags(profile.backend, configured_args))
    return _dedupe_preserving_order(merged)


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
