"""Facade re-exporting memory_search_policy for backward-compatible harness surface.

[INPUT]
- toolkits.memory.agent_surface.memory_search_policy::MemorySearchBackends,
  MemorySearchCorpus, MemorySearchPolicy, resolve_search_corpora
  (POS: 记忆检索策略权威实现层)

[OUTPUT]
- MemorySearchPolicy, MemorySearchBackends, MemorySearchCorpus, resolve_search_corpora

[POS]
Compatibility re-export shim. The authoritative implementation lives in
agent_surface/memory_search_policy.py; this module exists only so legacy import paths keep
working and must not gain logic of its own.
"""

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

