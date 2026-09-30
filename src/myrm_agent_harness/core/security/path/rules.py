"""Protected-path policy SSOT — which files an agent may not touch, and why.

Every protection rule in the harness resolves through this module, so the
permission engine (Layer 2.5 PathPolicy), the file-operation validators, the
Goal integrity checks and the shell pre-flight all return the same verdict for
the same path. Rules are data; the predicates below are the only way to read
them, which keeps a caller from matching a half-remembered pattern list.

[INPUT]
- path.filesystem::is_content_not_path (POS: Generic filesystem path safety — no product protection policy)
- path.pattern::first_matching_pattern (POS: Path pattern matching — single source of truth for glob-style path protection)

[OUTPUT]
- SENSITIVE_FILE_PATTERNS: tuple[str, ...] — credentials and secrets
- PROTECTED_INSTRUCTION_PATTERNS: tuple[str, ...] — persona/guardrail instruction files
- EVIDENCE_READONLY_PATTERNS: tuple[str, ...] — read-only session evidence and user inputs
- is_sensitive_file(path) -> bool
- is_protected_instruction_file(path) -> bool
- is_evidence_readonly_file(path) -> bool

[POS]
Protected-path policy. Delegates matching to `pattern`, path coercion to `filesystem`.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.path.filesystem import is_content_not_path
from myrm_agent_harness.core.security.path.pattern import first_matching_pattern

__all__ = (
    "EVIDENCE_READONLY_PATTERNS",
    "PROTECTED_INSTRUCTION_PATTERNS",
    "SENSITIVE_FILE_PATTERNS",
    "is_evidence_readonly_file",
    "is_protected_instruction_file",
    "is_sensitive_file",
)

# ---------------------------------------------------------------------------
# Sensitive file patterns
# ---------------------------------------------------------------------------

SENSITIVE_FILE_PATTERNS: tuple[str, ...] = (
    # Credentials and keys
    "**/id_rsa",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/id_ed25519",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    # Environment files
    "**/.env*",
    "**/credentials.json",
    "**/secrets.json",
    "**/config.json",
    # AWS credentials
    "**/.aws/credentials",
    "**/.aws/config",
    # Git config (may contain tokens)
    "**/.git/config",
    # Database files
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    # Password files
    "**/password.txt",
    "**/passwd",
    "**/shadow",
)

# ---------------------------------------------------------------------------
# Protected instruction file patterns (anti-persona tampering & prompt injection persistence)
# ---------------------------------------------------------------------------

PROTECTED_INSTRUCTION_PATTERNS: tuple[str, ...] = (
    "**/AGENTS.md",
    "**/CLAUDE.md",
    "**/SOUL.md",
    "**/USER.md",
    "**/.user.md",
    "**/MEMORY.md",
    "**/.myrm.md",
    "**/myrm.md",
    "**/.hermes.md",
    "**/HERMES.md",
    "**/.cursorrules",
    "**/.clinerules",
    "**/.windsurfrules",
    "**/.cursor/rules/**",
    "**/.myrm/rules/**",
    "**/.claude/CLAUDE.md",
    "**/.github/copilot-instructions.md",
)

# ---------------------------------------------------------------------------
# Session Evidence and Read-only Input File Patterns
# ---------------------------------------------------------------------------

EVIDENCE_READONLY_PATTERNS: tuple[str, ...] = (
    "**/evidence/**",
    "**/evidence/*",
    "evidence/**",
    "evidence/*",
    "**/user_inputs/**",
    "**/user_inputs/*",
    "user_inputs/**",
    "user_inputs/*",
    "**/.evidence/**",
    "**/.evidence/*",
)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_sensitive_file(path: str) -> bool:
    """Check if *path* matches any sensitive file pattern.

    Matching ignores case: on the case-insensitive filesystems that host the
    desktop and local-server builds (APFS, NTFS) ``Key.Pem`` and ``key.pem`` are
    one and the same file, so a case-sensitive rule would let a credential be
    renamed into a spelling the guard no longer recognises. Failing closed is
    the only safe direction for a guard whose failure mode is secret exposure.
    """
    if not path or not path.strip() or is_content_not_path(path):
        return False
    return first_matching_pattern(path, SENSITIVE_FILE_PATTERNS) is not None


def is_protected_instruction_file(path: str) -> bool:
    """Check if *path* refers to a protected instruction file (case-insensitive & normalised).

    Protected instruction files steer the future persona and behavioral guardrails
    of AI agents (e.g. AGENTS.md, SOUL.md, .cursorrules). Modifications to these files
    are high-risk persistence vectors for indirect prompt injection and MUST
    require human approval.

    The symlink target is checked as well as the given path, so a harmless-looking
    link cannot be used to rewrite an instruction file indirectly.
    """
    if not path or not str(path).strip() or is_content_not_path(path):
        return False
    if first_matching_pattern(path, PROTECTED_INSTRUCTION_PATTERNS) is not None:
        return True
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        return False
    if resolved == path:
        return False
    return first_matching_pattern(resolved, PROTECTED_INSTRUCTION_PATTERNS) is not None


def is_evidence_readonly_file(path: str) -> bool:
    """Check if *path* falls under a protected session evidence or user input directory.

    Evidence directories (e.g. `evidence/`, `user_inputs/`) store read-only raw factual
    sources pulled by tools or provided by users. The Agent must NOT overwrite or modify
    these raw materials during multi-step execution.

    Matching ignores case for the same reason as :func:`is_sensitive_file`: on
    case-insensitive filesystems ``Evidence/`` and ``evidence/`` denote one directory,
    so a case-sensitive rule could be side-stepped by changing only the spelling.
    """
    if not path or not str(path).strip() or is_content_not_path(path):
        return False
    normalised = str(path).replace("\\", "/")
    return first_matching_pattern(normalised, EVIDENCE_READONLY_PATTERNS) is not None
