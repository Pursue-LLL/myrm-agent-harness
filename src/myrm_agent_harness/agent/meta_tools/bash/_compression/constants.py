"""Compression domain constants.

[INPUT]
- None (stdlib only)

[OUTPUT]
- BASH_OUTPUT_MAX_CHARS: Character-level hard truncation threshold for bash output.

[POS]
Single source of truth for the bash output hard truncation limit. Used by the
compression/eviction domain as its character-level gate, and consumed by the
formatting layer so every output that would be hard-truncated downstream is
first persisted on disk and remains reachable.
"""

# Single source of truth for the bash output hard truncation limit.
# The eviction gate uses the same threshold so every output that would be
# hard-truncated by the formatting layer is first persisted on disk.
BASH_OUTPUT_MAX_CHARS = 8000
