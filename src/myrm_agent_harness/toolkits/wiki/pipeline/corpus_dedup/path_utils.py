"""Raw corpus path normalization for dedup governance.

[INPUT]
- (none)

[OUTPUT]
- normalize_raw_relative_path: raw-dir-relative path key without redundant raw/ prefix

[POS]
Path key SSOT for corpus_dedup store, eligibility filter, governor trash, and stale summary.
"""

from __future__ import annotations


def normalize_raw_relative_path(relative_path: str) -> str:
    """Return a path relative to vault raw/ without a redundant raw/ prefix."""
    cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
    if cleaned.startswith("raw/"):
        return cleaned.removeprefix("raw/")
    return cleaned
