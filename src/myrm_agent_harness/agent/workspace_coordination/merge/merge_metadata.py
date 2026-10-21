"""Transient ISOLATED_COPY merge metadata keys shared across spawn store and batch merge.

[INPUT]
- (none — pure constants/helpers)

[OUTPUT]
- MERGE_TRANSIENT_INNER_KEYS: frozenset of non-JSON inner result keys
- strip_merge_transient_inner_keys: remove merge metadata from inner result dicts

[POS]
SSOT for ISOLATED_COPY deferred merge metadata keys used before SQLite persistence and after batch merge/discard.
"""

from __future__ import annotations

MERGE_TRANSIENT_INNER_KEYS = frozenset(
    {
        "_workspace_sync_back",
        "_isolated_child_workspace",
        "_isolated_parent_workspace",
    }
)


def strip_merge_transient_inner_keys(inner: dict[str, object]) -> dict[str, object]:
    """Return inner result dict without non-JSON merge metadata."""
    return {k: v for k, v in inner.items() if k not in MERGE_TRANSIENT_INNER_KEYS}
