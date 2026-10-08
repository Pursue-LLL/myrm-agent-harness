"""Validator for official agent session resumption and command safety."""

from collections.abc import Sequence
from pathlib import Path

MAX_SESSION_ID_LEN: int = 512
MAX_SESSION_PATH_LEN: int = 4096
MAX_RESUME_ARGS: int = 64
MAX_RESUME_ARGV_BYTES: int = 8192

OFFICIAL_SOURCE_PAIRS: frozenset[tuple[str, str]] = frozenset({
    # Myrm native agents
    ("myrm:claude", "claude"),
    ("myrm:codex", "codex"),
    ("myrm:copilot", "copilot"),
    ("myrm:devin", "devin"),
    ("myrm:droid", "droid"),
    ("myrm:kimi", "kimi"),
    ("myrm:omp", "omp"),
    ("myrm:pi", "pi"),
    ("myrm:opencode", "opencode"),
    ("myrm:qodercli", "qodercli"),
    ("myrm:qwen", "qwen"),
    ("myrm:cursor", "cursor"),
    ("myrm:agy", "agy"),
    ("myrm:grok", "grok"),
    ("myrm:letta", "letta"),
    ("myrm:mastracode", "mastracode"),
    ("myrm:hermes", "hermes"),
    ("myrm:kilo", "kilo"),
    # Herdr compatibility sources
    ("herdr:claude", "claude"),
    ("herdr:codex", "codex"),
    ("herdr:copilot", "copilot"),
    ("herdr:devin", "devin"),
    ("herdr:droid", "droid"),
    ("herdr:kimi", "kimi"),
    ("herdr:omp", "omp"),
    ("herdr:pi", "pi"),
    ("herdr:opencode", "opencode"),
    ("herdr:qodercli", "qodercli"),
    ("herdr:qwen", "qwen"),
    ("herdr:cursor", "cursor"),
    ("herdr:antigravity_cli", "agy"),
    ("herdr:agy", "agy"),
    ("herdr:grok", "grok"),
    ("herdr:letta", "letta"),
    ("herdr:mastracode", "mastracode"),
    ("herdr:hermes", "hermes"),
    ("herdr:kilo", "kilo"),
})

VALID_START_SOURCES: frozenset[str] = frozenset({
    "startup",
    "resume",
    "clear",
    "compact",
    "branch",
    "new",
    "fork",
    "select",
})


def is_official_agent_source(source: str, agent: str) -> bool:
    """Check if the source and agent pair matches official registered sources."""
    return (source, agent) in OFFICIAL_SOURCE_PAIRS


def is_valid_session_id(value: str) -> bool:
    """Validate that session ID meets length and control character constraints."""
    if not value or len(value) > MAX_SESSION_ID_LEN:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in value)


def is_valid_session_path(value: str) -> bool:
    """Validate that session path is absolute, within limit, and contains no control chars."""
    if not value or len(value) > MAX_SESSION_PATH_LEN:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    return Path(value).is_absolute()


def normalize_session_start_source(value: str | None) -> str | None:
    """Normalize session start source string into a valid enum value if recognized."""
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in VALID_START_SOURCES else None


def validate_resume_argv(argv: Sequence[str]) -> tuple[bool, str | None]:
    """Validate resume command line arguments against injection, size, and syntax rules."""
    if not argv:
        return False, "resume_argv must not be empty"
    if len(argv) > MAX_RESUME_ARGS:
        return False, f"resume_argv allows at most {MAX_RESUME_ARGS} arguments"
    total_bytes = sum(len(arg.encode("utf-8")) for arg in argv)
    if total_bytes > MAX_RESUME_ARGV_BYTES:
        return False, f"resume_argv allows at most {MAX_RESUME_ARGV_BYTES} bytes"
    for arg in argv:
        if any(ord(c) < 32 or ord(c) == 127 for c in arg):
            return False, "resume_argv must not contain control characters"
        if "'" in arg:
            return False, "resume_argv must not contain apostrophes"

    command = argv[0]
    if not command or command.startswith("-"):
        return False, "resume_argv must start with a plain command name, not an option"
    # Plain command name, not a path
    is_plain = all(c.isalnum() or c in ("_", "-", ".") for c in command)
    if not is_plain:
        return False, "resume_argv must start with a plain command name, not a path"

    return True, None
