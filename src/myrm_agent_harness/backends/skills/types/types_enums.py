"""Skill trust, lifecycle, and permission enumerations.

[INPUT]
- (none)

[OUTPUT]
- SkillTrust: trust level enum (INSTALLED/TRUSTED)
- SkillLifecycleStatus: curator lifecycle enum (ACTIVE/STALE/ARCHIVED)
- SkillPermission: declared permission types for skills

[POS]
Core skill enumeration types used across backends and agent layers.
"""

from enum import IntEnum, StrEnum


class SkillTrust(IntEnum):
    """Trust level for a skill, determining its tool authority ceiling.

    SAFETY: Variant ordering matters. The security model relies on
    ``INSTALLED < TRUSTED`` for min() comparisons in trust attenuation.
    Do NOT reorder variants.
    """

    INSTALLED = 0
    """Registry/external skill — restricted to read-only tools."""

    TRUSTED = 1
    """User-placed skill (local/workspace) — full tool access."""


class SkillLifecycleStatus(StrEnum):
    """Lifecycle state for skill curator management.

    Tracks the gradual degradation of unused or low-quality skills:
    active → stale → archived.  Stale skills remain usable but are
    deprioritised in selection; archived skills are excluded from runtime
    entirely but retain their data for recovery.
    """

    ACTIVE = "active"
    """Normal state — fully operational and discoverable."""

    STALE = "stale"
    """Marked as stale — still usable but deprioritised and shown with a warning.
    Auto-recovers to ACTIVE when the skill is successfully used again."""

    ARCHIVED = "archived"
    """Excluded from runtime — data preserved, recoverable via restore."""


class SkillPermission(StrEnum):
    """Permission types that skills can request.

    Skills declare required permissions in SKILL.md frontmatter.
    The system validates these at install time and enforces them at runtime.
    """

    FILE_READ = "file_read"
    """Read files from the workspace"""

    FILE_WRITE = "file_write"
    """Write/modify files in the workspace"""

    FILE_DELETE = "file_delete"
    """Delete files from the workspace"""

    SHELL_EXEC = "shell_exec"
    """Execute shell commands"""

    CODE_INTERPRETER = "code_interpreter"
    """Execute code in sandboxed interpreters (Python, Node.js, etc.)"""

    NETWORK_ACCESS = "network_access"
    """Make network requests (HTTP/HTTPS)"""

    ENV_VAR_ACCESS = "env_var_access"
    """Read/write environment variables"""
