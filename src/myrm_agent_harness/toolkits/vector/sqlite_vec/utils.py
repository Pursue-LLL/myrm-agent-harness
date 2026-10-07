"""Internal serialization and similarity utilities for SQLite vector store.

[POS]
Low-level binary vector packing, cosine similarity mathematics,
and metadata filter matching utilities for SQLite vector storage.

[INPUT]
- math, struct
- myrm_agent_harness.toolkits.vector.base (FilterDict, FilterValue)

[OUTPUT]
- pack_vector: Pack float list into IEEE-754 float32 bytes blob
- unpack_vector: Unpack float32 bytes blob into float list
- cosine_similarity: Fast bounded cosine similarity calculation
- match_filter: Evaluate document metadata against filter dictionary
"""

from __future__ import annotations

import math
import struct

from myrm_agent_harness.toolkits.vector.base import FilterDict, FilterValue


def pack_vector(vector: list[float]) -> bytes:
    """Pack float array into compact binary float32 blob."""
    return struct.pack(f"{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack compact binary float32 blob into float array."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors normalized in [0.0, 1.0]."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b, strict=True):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    cos = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return max(0.0, min(1.0, (cos + 1.0) / 2.0))


def match_filter(metadata: dict[str, FilterValue], filters: FilterDict | None) -> bool:
    """Evaluate whether document metadata satisfies filter dictionary."""
    if not filters:
        return True
    for key, expected in filters.items():
        actual = metadata.get(key)
        if actual is None:
            return False
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
