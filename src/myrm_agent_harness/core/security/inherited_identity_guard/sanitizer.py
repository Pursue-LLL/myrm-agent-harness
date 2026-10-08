"""Sanitizer implementation for inherited terminal and session identity."""

from collections.abc import Mapping
from pathlib import Path

from .types import (
    AgentResumePlan,
    AgentSessionRef,
    AgentSessionRefKind,
    PersistedAgentSession,
    SanitizationPolicy,
    SanitizationResult,
)
from .validator import (
    is_official_agent_source,
    is_valid_session_id,
    is_valid_session_path,
    validate_resume_argv,
)

DEFAULT_DENIED_ENV_KEYS: frozenset[str] = frozenset({
    # Agent session identifiers
    "CODEX_THREAD_ID",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "MYRM_SESSION_ID",
    "MYRM_PANE_ID",
    "MYRM_SESSION_SOCKET",
    "MYRM_PARENT_SESSION",
    "HERDR_SOCKET_PATH",
    "HERDR_SESSION",
    "HERDR_SOCKET",
    "HERDR_SESSION_ID",
    "CLAW_SESSION_ID",
    "CLAW_SOCKET",
    # Terminal pane identifiers
    "TMUX",
    "TMUX_PANE",
    "WT_SESSION",
    "WT_PROFILE_ID",
    "WEZTERM_PANE",
    "WEZTERM_EXECUTABLE",
    "WEZTERM_UNIX_SOCKET",
    "GHOSTTY_PANE",
    "GHOSTTY_RESOURCES_DIR",
    "KITTY_WINDOW_ID",
    "KITTY_PID",
    "STY",
    "WINDOW",
    "TERM_SESSION_ID",
    "ITERM_SESSION_ID",
    "WINDOWID",
    "ALACRITTY_LOG",
    "ALACRITTY_WINDOW_ID",
})

STANDARD_SYSTEM_ENV_KEYS: frozenset[str] = frozenset({
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TERM",
    "COLORTERM",
    "TMPDIR",
    "TEMP",
    "TMP",
    "TZ",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
})


class InheritedIdentitySanitizer:
    """Sanitizes terminal environments and validates official session resumptions."""

    def __init__(
        self,
        default_policy: SanitizationPolicy | None = None,
    ) -> None:
        self._policy = default_policy or SanitizationPolicy(
            denied_env_keys=DEFAULT_DENIED_ENV_KEYS,
            allow_system_only=False,
        )

    @property
    def policy(self) -> SanitizationPolicy:
        """Get the active sanitization policy."""
        return self._policy

    def sanitize_env(
        self,
        dirty_env: Mapping[str, str],
        extra: Mapping[str, str] | None = None,
    ) -> SanitizationResult:
        """Purge inherited terminal and agent session variables from the given environment."""
        sanitized: dict[str, str] = {}
        purged: list[str] = []

        denied_keys = self._policy.denied_env_keys or DEFAULT_DENIED_ENV_KEYS

        for key, value in dirty_env.items():
            if key in denied_keys:
                purged.append(key)
                continue
            if any(key.startswith(p) for p in self._policy.extra_denied_prefixes):
                purged.append(key)
                continue
            if self._policy.allow_system_only and key not in STANDARD_SYSTEM_ENV_KEYS:
                purged.append(key)
                continue
            sanitized[key] = value

        if extra:
            for extra_key, extra_val in extra.items():
                sanitized[extra_key] = extra_val

        purged.sort()
        return SanitizationResult(
            sanitized_env=sanitized,
            purged_keys=purged,
            purged_count=len(purged),
            is_isolated=True,
        )

    def resolve_session_ref(
        self,
        source: str,
        agent: str,
        session_id: str | None = None,
        session_path: str | None = None,
    ) -> AgentSessionRef | None:
        """Resolve and validate an AgentSessionRef from reported session parameters."""
        if not is_official_agent_source(source, agent):
            return None

        if agent in ("pi", "omp"):
            if session_path and is_valid_session_path(session_path):
                return AgentSessionRef(kind=AgentSessionRefKind.PATH, value=session_path)
            if session_id and is_valid_session_id(session_id):
                return AgentSessionRef(kind=AgentSessionRefKind.ID, value=session_id)
            return None

        if session_id and is_valid_session_id(session_id):
            return AgentSessionRef(kind=AgentSessionRefKind.ID, value=session_id)

        return None

    def build_persisted_session(
        self,
        source: str,
        agent: str,
        session_ref: AgentSessionRef,
    ) -> PersistedAgentSession | None:
        """Construct a validated PersistedAgentSession from official origins."""
        if not is_official_agent_source(source, agent):
            return None
        return PersistedAgentSession(
            source=source,
            agent=agent,
            session_ref=session_ref,
        )

    def create_resume_plan(
        self,
        source: str,
        agent: str,
        session_ref: AgentSessionRef,
        cwd: str | Path | None = None,
        is_windows: bool = False,
    ) -> AgentResumePlan | None:
        """Derive an executable and validated resume plan for an official session."""
        if not is_official_agent_source(source, agent):
            return None

        argv = self.resolve_argv(agent, session_ref, is_windows=is_windows)
        if argv is None:
            return None

        is_valid, _ = validate_resume_argv(argv)
        if not is_valid:
            return None

        if cwd is not None:
            cwd_str = str(cwd)
            dedupe_key = f"{source}\x00{agent}\x00{cwd_str}\x00argv\x00{chr(0).join(argv)}"
        else:
            dedupe_key = f"{source}\x00{agent}\x00{session_ref.kind.value}\x00{session_ref.value}"

        return AgentResumePlan(
            agent=agent,
            argv=argv,
            dedupe_key=dedupe_key,
        )

    def resolve_argv(
        self,
        agent: str,
        session_ref: AgentSessionRef,
        is_windows: bool = False,
    ) -> list[str] | None:
        """Resolve command line arguments for the given agent and session ref."""
        val = session_ref.value
        kind = session_ref.kind

        if agent == "claude" and kind == AgentSessionRefKind.ID:
            return ["claude", "--resume", val]
        if agent == "codex" and kind == AgentSessionRefKind.ID:
            return ["codex", "resume", val]
        if agent == "copilot" and kind == AgentSessionRefKind.ID:
            return ["copilot", f"--resume={val}"]
        if agent == "devin" and kind == AgentSessionRefKind.ID:
            return ["devin", "--resume", val]
        if agent == "droid" and kind == AgentSessionRefKind.ID:
            return ["droid", "--resume", val]
        if agent == "kimi" and kind == AgentSessionRefKind.ID:
            return ["kimi", "--session", val]
        if agent == "mastracode" and kind == AgentSessionRefKind.ID:
            return ["mastracode", "--thread", val]
        if agent == "pi" and kind in (AgentSessionRefKind.PATH, AgentSessionRefKind.ID):
            return ["pi", "--session", val]
        if agent == "omp" and kind in (AgentSessionRefKind.PATH, AgentSessionRefKind.ID):
            return ["omp", f"--resume={val}"]
        if agent == "hermes" and kind == AgentSessionRefKind.ID:
            return ["hermes", "--resume", val]
        if agent == "opencode" and kind == AgentSessionRefKind.ID:
            return ["opencode", "--session", val]
        if agent == "qodercli" and kind == AgentSessionRefKind.ID:
            return ["qodercli", "--resume", val]
        if agent == "qwen" and kind == AgentSessionRefKind.ID:
            return ["qwen", "--resume", val]
        if agent == "kilo" and kind == AgentSessionRefKind.ID:
            return ["kilo", "--session", val]
        if agent == "cursor" and kind == AgentSessionRefKind.ID:
            cmd = "cursor-agent.cmd" if is_windows else "cursor-agent"
            return [cmd, "--resume", val]
        if agent == "agy" and kind == AgentSessionRefKind.ID:
            return ["agy", "--conversation", val]
        if agent == "grok" and kind == AgentSessionRefKind.ID:
            return ["grok", "--resume", val]
        if agent == "letta" and kind == AgentSessionRefKind.ID:
            if val.startswith("default:"):
                agent_id = val[len("default:") :]
                if not agent_id:
                    return None
                return ["letta", "--conversation", "default", "--agent", agent_id]
            return ["letta", "--conversation", val]

        return None
