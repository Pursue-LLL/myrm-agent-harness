"""Script physical integrity and fingerprint hashing domain.

Extracts local script targets from shell execution commands and computes
deterministic SHA-256 fingerprints to defend against Time-Of-Check to Time-Of-Use
(TOCTOU) script tampering attacks between approval and execution.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import shlex
from dataclasses import dataclass

_KNOWN_INTERPRETERS: frozenset[str] = frozenset(
    {
        "python",
        "python3",
        "python3.11",
        "python3.12",
        "python3.13",
        "bash",
        "sh",
        "zsh",
        "node",
        "bun",
        "ts-node",
        "perl",
        "ruby",
    }
)

_INTERPRETER_FLAGS_TAKING_VALUE: frozenset[str] = frozenset(
    {
        "-m",
        "-c",
        "-e",
        "-W",
        "-X",
        "--import",
    }
)

MAX_SCRIPT_HASH_BYTES: int = 10 * 1024 * 1024  # 10 MB limit to prevent DoS


@dataclass(frozen=True)
class ScriptTargetInfo:
    """Target script file path and its content SHA-256 digest."""

    relative_path: str
    absolute_path: str
    content_hash: str


def compute_file_sha256(file_path: str, max_bytes: int = MAX_SCRIPT_HASH_BYTES) -> str | None:
    """Compute SHA-256 hex digest of a physical file up to max_bytes.

    Returns:
        Hex digest string or None if unreadable / non-existent.
    """
    if not os.path.isfile(file_path):
        return None
    try:
        stat_res = os.stat(file_path)
        if stat_res.st_size > max_bytes:
            return None
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return None


def extract_script_target_and_hash(
    command: str,
    workspace_root: str | None = None,
) -> ScriptTargetInfo | None:
    """Analyze a shell command, identify referenced local script, and compute its hash.

    Handles environment variables (KEY=VAL), common interpreter arguments,
    relative/absolute paths, and symlink canonicalization.

    Args:
        command: The raw shell command string
        workspace_root: The safe workspace directory (if provided)

    Returns:
        ScriptTargetInfo if a local script was detected and hashed, else None.
    """
    if not command or not command.strip():
        return None

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None

    if not tokens:
        return None

    idx = 0
    # 1. Skip environment variable assignments
    while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith(("-", "/")):
        idx += 1

    if idx >= len(tokens):
        return None

    first_token = tokens[idx]
    base_exec = os.path.basename(first_token)

    candidate_path: str | None = None

    if base_exec in _KNOWN_INTERPRETERS:
        idx += 1
        # Skip interpreter options
        while idx < len(tokens):
            token = tokens[idx]
            if token in ("-c", "-e"):
                # Inline evaluation string, not a script file
                return None
            if token.startswith("-"):
                if token in _INTERPRETER_FLAGS_TAKING_VALUE:
                    idx += 2
                    continue
                idx += 1
                continue
            # Found first non-flag argument
            candidate_path = token
            break
    elif first_token.endswith((".sh", ".py", ".js", ".ts", ".bash", ".zsh", ".rb")):
        candidate_path = first_token
    elif first_token.startswith("./") or first_token.startswith("../"):
        candidate_path = first_token

    if not candidate_path:
        return None

    # Resolve paths
    norm_candidate = candidate_path.strip()
    if workspace_root and not os.path.isabs(norm_candidate):
        full_path = os.path.normpath(os.path.join(workspace_root, norm_candidate))
    else:
        full_path = os.path.normpath(os.path.abspath(norm_candidate))

    # Resolve symlinks to physical target
    try:
        real_path = os.path.realpath(full_path)
    except OSError:
        real_path = full_path

    # Security boundary: must remain within workspace_root if provided
    if workspace_root:
        real_ws = os.path.realpath(workspace_root)
        try:
            rel = os.path.relpath(real_path, real_ws)
            if rel.startswith("..") or os.path.isabs(rel):
                # Path escapes workspace root
                return None
        except ValueError:
            return None

    content_hash = compute_file_sha256(real_path)
    if not content_hash:
        return None

    rel_display = os.path.relpath(real_path, workspace_root) if workspace_root else norm_candidate
    return ScriptTargetInfo(
        relative_path=rel_display,
        absolute_path=real_path,
        content_hash=content_hash,
    )
