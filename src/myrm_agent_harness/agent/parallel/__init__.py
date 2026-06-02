"""Parallel task execution package for batch delegate and swarm fission."""

from myrm_agent_harness.agent.parallel.config import (
    DEFAULT_MAX_PARALLEL_FISSION,
    MAX_PARALLEL_FISSION_CAP,
    resolve_max_parallel_fission,
)
from myrm_agent_harness.agent.parallel.schemas import (
    ParallelTaskResultItem,
    ParallelTaskResults,
)
from myrm_agent_harness.agent.parallel.summary import (
    batch_summary,
    inject_capacity_signal,
)

__all__ = [
    "DEFAULT_MAX_PARALLEL_FISSION",
    "MAX_PARALLEL_FISSION_CAP",
    "ParallelTaskResultItem",
    "ParallelTaskResults",
    "batch_summary",
    "inject_capacity_signal",
    "resolve_max_parallel_fission",
]
