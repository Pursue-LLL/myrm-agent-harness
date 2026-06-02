"""Line ending detection and normalization utilities.

Preserves the original line ending style (LF / CRLF) of a file across
edits performed by the agent. Agent tool parameters arrive via JSON which
does not transmit `\\r` (RFC 8259 §7), so without explicit normalization
every edit on a CRLF file introduces mixed line endings.

[OUTPUT]
- detect_line_ending: function — Detect dominant line ending
- normalize_line_endings: function — Convert all line endings to target
"""

from __future__ import annotations

_SAMPLE_SIZE = 4096


def detect_line_ending(content: str) -> str | None:
    """Return the dominant line ending in *content*, or ``None`` if undetermined.

    Scans the first 4 KiB — enough to decide, cheap to scan.
    Returns ``"\\r\\n"`` when any CRLF is present, ``"\\n"`` for pure-LF,
    or ``None`` for single-line / empty content where the style is ambiguous.
    """
    if not content:
        return None
    head = content[:_SAMPLE_SIZE]
    if "\r\n" in head:
        return "\r\n"
    if "\n" in head:
        return "\n"
    return None


def normalize_line_endings(text: str, target: str) -> str:
    """Convert all line endings in *text* to *target* (``"\\n"`` or ``"\\r\\n"``).

    Idempotent: applying the same target twice yields identical output.
    Handles mixed endings (lone ``\\r``, mixed CRLF/LF) in a single pass.
    """
    # Collapse everything to LF first (CRLF → LF, lone CR → LF)
    lf_only = text.replace("\r\n", "\n").replace("\r", "\n")
    if target == "\r\n":
        return lf_only.replace("\n", "\r\n")
    return lf_only
