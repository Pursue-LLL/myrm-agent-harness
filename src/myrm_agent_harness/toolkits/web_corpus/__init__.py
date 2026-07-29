"""Web Corpus — persistent cross-session web page index.

Automatically indexes search results and fetched pages into a local
SQLite FTS5 store, enabling zero-API-cost re-queries across sessions.
Consumed via ``memory_search_tool(corpus='web')``.
"""

from .aging import CorpusAgingPolicy, run_aging
from .store import WebCorpusStore
from .types import CorpusStats, WebCorpusEntry

__all__ = [
    "CorpusAgingPolicy",
    "CorpusStats",
    "WebCorpusEntry",
    "WebCorpusStore",
    "run_aging",
]
