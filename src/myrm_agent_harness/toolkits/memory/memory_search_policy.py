"""Facade re-exporting memory_search_policy for backward-compatible harness surface."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchBackends,
    MemorySearchCorpus,
    MemorySearchPolicy,
    resolve_search_corpora,
)

__all__ = [
    "MemorySearchBackends",
    "MemorySearchCorpus",
    "MemorySearchPolicy",
    "resolve_search_corpora",
]

