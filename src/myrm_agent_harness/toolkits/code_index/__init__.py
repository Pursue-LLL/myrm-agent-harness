"""Code Index toolkit — workspace-level code search indexer.

Provides on-demand code indexing with FTS5 + optional vector hybrid search,
enabling semantic code search for agent tools and @codebase mentions.
"""

from myrm_agent_harness.toolkits.code_index.config import CodeIndexConfig
from myrm_agent_harness.toolkits.code_index.indexer import CodeIndexer

__all__ = ["CodeIndexConfig", "CodeIndexer"]
