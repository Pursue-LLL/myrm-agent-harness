"""Official source whitelists and validation utilities for session resumes.

Guarantees that session resumes and snapshots originate exclusively from vetted,
official agent sources, preventing untrusted or spoofed session injection.
"""

from pathlib import Path

MAX_SESSION_ID_LEN: int = 512
MAX_SESSION_PATH_LEN: int = 4096

VALID_SESSION_START_SOURCES: frozenset[str] = frozenset(
    {
        "startup",
        "resume",
        "clear",
        "compact",
        "branch",
        "new",
        "fork",
        "select",
    }
)

OFFICIAL_AGENT_SOURCES: dict[str, frozenset[str]] = {
    # Myrm native namespaces
    "myrm:claude": frozenset({"claude"}),
    "myrm:codex": frozenset({"codex"}),
    "myrm:copilot": frozenset({"copilot"}),
    "myrm:devin": frozenset({"devin"}),
    "myrm:droid": frozenset({"droid"}),
    "myrm:kimi": frozenset({"kimi"}),
    "myrm:omp": frozenset({"omp"}),
    "myrm:pi": frozenset({"pi"}),
    "myrm:hermes": frozenset({"hermes"}),
    "myrm:opencode": frozenset({"opencode"}),
    "myrm:qodercli": frozenset({"qodercli"}),
    "myrm:qwen": frozenset({"qwen"}),
    "myrm:kilo": frozenset({"kilo"}),
    "myrm:cursor": frozenset({"cursor"}),
    "myrm:agy": frozenset({"agy"}),
    "myrm:grok": frozenset({"grok"}),
    "myrm:letta": frozenset({"letta"}),
    # Interoperable official namespaces
    "herdr:claude": frozenset({"claude"}),
    "herdr:codex": frozenset({"codex"}),
    "herdr:copilot": frozenset({"copilot"}),
    "herdr:devin": frozenset({"devin"}),
    "herdr:droid": frozenset({"droid"}),
    "herdr:kimi": frozenset({"kimi"}),
    "herdr:omp": frozenset({"omp"}),
    "herdr:mastracode": frozenset({"mastracode"}),
    "herdr:pi": frozenset({"pi"}),
    "herdr:hermes": frozenset({"hermes"}),
    "herdr:opencode": frozenset({"opencode"}),
    "herdr:qodercli": frozenset({"qodercli"}),
    "herdr:qwen": frozenset({"qwen"}),
    "herdr:kilo": frozenset({"kilo"}),
    "herdr:cursor": frozenset({"cursor"}),
    "herdr:antigravity_cli": frozenset({"agy"}),
    "herdr:grok": frozenset({"grok"}),
    "herdr:letta": frozenset({"letta"}),
}


def is_official_agent_source(source: str, agent: str) -> bool:
    """Verify whether a (source, agent) pair belongs to official whitelist."""
    allowed_agents: frozenset[str] | None = OFFICIAL_AGENT_SOURCES.get(source)
    if allowed_agents is None:
        return False
    return agent in allowed_agents


def normalize_session_start_source(value: str | None) -> str | None:
    """Normalize session start source name against permitted enum values."""
    if value is None:
        return None
    trimmed: str = value.strip().lower()
    if trimmed in VALID_SESSION_START_SOURCES:
        return trimmed
    return None


def is_valid_session_id(value: str) -> bool:
    """Validate session identifier string length and character safety."""
    if not value or len(value) > MAX_SESSION_ID_LEN:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def is_valid_session_path(value: str) -> bool:
    """Validate session path string format, safety, and absolute qualification."""
    if not value or len(value) > MAX_SESSION_PATH_LEN:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        path: Path = Path(value)
        return path.is_absolute()
    except Exception:
        return False
