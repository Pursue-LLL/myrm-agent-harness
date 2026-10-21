"""[INPUT] Raw text strings from CLI stdout/stderr.
[OUTPUT] ANSI-sanitized text and SHA-256 cryptographic receipt hashes.
[POS] Stream cleaner and evidence hash generator for external CLI agent bridge.
"""

from __future__ import annotations

import hashlib
import re

# Comprehensive regex matching ANSI CSI, OSC, and cursor navigation escape sequences
_ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][0-9;]*\x07)"
)

# Control characters removal except newline, carriage return, and tab
_C0_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def sanitize_cli_output(raw_text: str, max_chars: int = 8192) -> str:
    """Strip terminal ANSI sequences and control codes, bounding total output length."""
    if not raw_text:
        return ""

    # 1. Strip ANSI escape codes
    text = _ANSI_ESCAPE_RE.sub("", raw_text)

    # 2. Strip invasive C0 control characters
    text = _C0_CONTROL_RE.sub("", text)

    # 3. Normalize carriage returns
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 4. Bound output to prevent context window overflow
    if len(text) > max_chars:
        half = max_chars // 2
        return (
            text[:half]
            + f"\n... [TRUNCATED {len(text) - max_chars} CHARACTERS] ...\n"
            + text[-half:]
        )
    return text.strip()


def compute_receipt_hash(
    execution_id: str,
    agent_id: str,
    exit_code: int | None,
    stdout_summary: str,
) -> str:
    """Compute deterministic SHA-256 hash verifying the execution facts."""
    hasher = hashlib.sha256()
    hasher.update(execution_id.encode("utf-8"))
    hasher.update(agent_id.encode("utf-8"))
    hasher.update(str(exit_code).encode("utf-8"))
    hasher.update(stdout_summary.encode("utf-8"))
    return hasher.hexdigest()
