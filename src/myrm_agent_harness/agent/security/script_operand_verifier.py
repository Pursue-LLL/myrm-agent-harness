"""Script Operand Verifier — prevents approved scripts from changing before execution (TOCTOU defense).

[INPUT]
- command string from tool input (e.g., bash/shell execution)
- workspace_root / cwd for resolving relative file operands

[OUTPUT]
- extract_script_file_operand: Extract and resolve canonical real path of mutable script operand.
- compute_file_content_digest: Compute SHA-256 digest of file content with size limit.
- verify_script_operand_integrity: Revalidate current file bytes against approval snapshot.

[POS]
Security gate preventing Time-of-Check to Time-of-Use (TOCTOU) attacks on mutable script operands.
Protects human-in-the-loop approvals so executing scripts cannot drift after operator review (CVE-2026-32921).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)

# Default maximum file size to hash (64 MiB) to guard against unbounded I/O
MAX_SCRIPT_HASH_BYTES = 64 * 1024 * 1024
CHUNK_SIZE = 64 * 1024

_INTERPRETERS = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "python",
        "python3",
        "node",
        "nodejs",
        "bun",
        "deno",
        "perl",
        "ruby",
    }
)

_INLINE_FLAGS = frozenset({"-c", "-e", "--eval", "-eval"})

_ENV_VAR_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")

_SCRIPT_EXTENSIONS = frozenset(
    {
        ".sh",
        ".bash",
        ".zsh",
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".pl",
        ".rb",
    }
)


def extract_script_file_operand(
    command: str,
    workspace_root: str | None = None,
) -> str | None:
    """Extract canonical real path of a mutable script operand referenced in a command.

    Handles:
    - Environment variable prefixes: ``VAR=val python script.py``
    - Interpreter invocations: ``bash ./run.sh``, ``python3 main.py``
    - Inline evaluation flags: ``python -c '...'`` -> returns None (inline, not a file operand)
    - Direct script invocations: ``./build.sh``, ``scripts/migrate.py``
    - Symlink resolution: traverses to the underlying real canonical path.

    Returns:
        Canonical absolute path to existing file, or None if no mutable file operand is detected.
    """
    stripped = command.strip()
    if not stripped:
        return None

    # Fast check: pipeline operators generally indicate multi-command streaming
    # We still inspect the first segment if cleanly splittable
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # Malformed quoting; cannot reliably extract file operand
        return None

    if not tokens:
        return None

    # Step 1: Skip leading environment variable assignments
    idx = 0
    while idx < len(tokens) and _ENV_VAR_ASSIGNMENT_RE.match(tokens[idx]):
        idx += 1

    if idx >= len(tokens):
        return None

    prog_token = tokens[idx]
    base_prog = os.path.basename(prog_token).lower()
    rest_args = tokens[idx + 1 :]

    candidate_file_token: str | None = None

    if base_prog in _INTERPRETERS:
        # Check for inline evaluation flags (e.g. python -c "print(1)")
        # If an inline flag is present before any non-flag token, this is inline code
        skip_next = False
        for arg in rest_args:
            if skip_next:
                skip_next = False
                continue
            if arg in _INLINE_FLAGS:
                return None
            if arg.startswith("-") and not arg.startswith("./"):
                # Flag parameter (e.g. -u, -v, --flag)
                continue
            # First non-flag argument to interpreter is the script operand
            candidate_file_token = arg
            break
    elif (
        prog_token.startswith("./")
        or prog_token.startswith("../")
        or prog_token.startswith("/")
        or any(prog_token.endswith(ext) for ext in _SCRIPT_EXTENSIONS)
    ):
        # Direct script invocation: ./deploy.sh, /tmp/run.py, scripts/build.sh
        candidate_file_token = prog_token

    if not candidate_file_token:
        return None

    # Resolve candidate file path against workspace_root or cwd
    return _resolve_existing_real_path(candidate_file_token, workspace_root)


def _resolve_existing_real_path(
    file_path: str,
    workspace_root: str | None = None,
) -> str | None:
    """Resolve file path to canonical realpath if it exists as a regular file."""
    try:
        if os.path.isabs(file_path):
            p = Path(file_path)
        elif workspace_root:
            p = Path(workspace_root) / file_path
        else:
            p = Path(os.getcwd()) / file_path

        real_p = p.resolve()
        if real_p.is_file():
            return str(real_p)
    except (OSError, ValueError):
        return None

    return None


def compute_file_content_digest(
    file_path: str,
    max_bytes: int = MAX_SCRIPT_HASH_BYTES,
) -> str | None:
    """Compute SHA-256 hex digest of file bytes with size threshold protection.

    Returns:
        Hex digest string (64 characters), or None if unreadable or exceeds max_bytes.
    """
    try:
        real_path = os.path.realpath(file_path)
        st = os.stat(real_path)
        if st.st_size > max_bytes:
            logger.warning(
                "[SCRIPT_OPERAND] File %s exceeds max hash limit (%d > %d bytes)",
                file_path,
                st.st_size,
                max_bytes,
            )
            return None

        h = hashlib.sha256()
        total_read = 0
        with open(real_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > max_bytes:
                    return None
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError) as exc:
        logger.debug("[SCRIPT_OPERAND] Failed to compute digest for %s: %s", file_path, exc)
        return None


def verify_script_operand_integrity(
    expected_hash: str,
    file_path: str,
    max_bytes: int = MAX_SCRIPT_HASH_BYTES,
) -> tuple[bool, str | None]:
    """Verify that current file content strictly matches expected approval snapshot.

    Returns:
        (True, None) if matching.
        (False, error_reason) if missing, unreadable, or modified (TOCTOU detected).
    """
    if not expected_hash:
        return False, "Approval script snapshot hash is empty or missing"

    if not os.path.exists(file_path):
        return False, f"Approved script file '{file_path}' no longer exists"

    current_hash = compute_file_content_digest(file_path, max_bytes=max_bytes)
    if not current_hash:
        return False, f"Approved script file '{file_path}' is unreadable or exceeds {max_bytes} bytes"

    if current_hash != expected_hash:
        return (
            False,
            f"Approved script file '{file_path}' was modified before execution "
            f"(TOCTOU detected: expected sha256={expected_hash[:12]}..., current={current_hash[:12]}...)",
        )

    return True, None
