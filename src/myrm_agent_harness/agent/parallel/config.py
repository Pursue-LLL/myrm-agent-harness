"""Parallel execution limits for batch delegate and swarm fission."""

from __future__ import annotations

DEFAULT_MAX_PARALLEL_FISSION = 3
MAX_PARALLEL_FISSION_CAP = 5
DEFAULT_MAX_BATCH_PARALLEL = 5


def resolve_max_parallel_fission(raw: int | None) -> int:
    """Clamp configured swarm fission concurrency to production-safe bounds."""
    if raw is None:
        return DEFAULT_MAX_PARALLEL_FISSION
    return max(1, min(int(raw), MAX_PARALLEL_FISSION_CAP))
