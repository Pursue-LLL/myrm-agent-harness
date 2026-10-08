# [INPUT]: None
# [OUTPUT]: ContextEvaluationResult, MateclawStaleQueryContextExpireSuite, QueryContextStatus, QueryIntentEntry, StaleQueryExpiryEngine
# [POS]: agent/context_management/stale_query_expire/__init__.py

"""Stale query context expiration package.

[INPUT]
- agent.context_management.stale_query_expire.query_context_types::ContextEvaluationResult,
  QueryContextStatus, QueryIntentEntry (POS: Strongly typed contracts for persistent session query context and
  staleness tracking.)
- agent.context_management.stale_query_expire.stale_query_context_suite::MateclawStaleQueryContextExpireSuite
  (POS: End-to-end suite orchestrating query context expiration in persistent long-running sessions.)
- agent.context_management.stale_query_expire.stale_query_expiry_engine::StaleQueryExpiryEngine (POS: Engine
  evaluating query context aging through dual turn-distance and TTL criteria.)

[OUTPUT]
- Re-exports: ContextEvaluationResult, MateclawStaleQueryContextExpireSuite, QueryContextStatus,
  QueryIntentEntry, StaleQueryExpiryEngine

[POS]
Stale query context expiration package.
"""

from __future__ import annotations

from .query_context_types import (
    ContextEvaluationResult,
    QueryContextStatus,
    QueryIntentEntry,
)
from .stale_query_context_suite import MateclawStaleQueryContextExpireSuite
from .stale_query_expiry_engine import StaleQueryExpiryEngine

__all__ = [
    "ContextEvaluationResult",
    "MateclawStaleQueryContextExpireSuite",
    "QueryContextStatus",
    "QueryIntentEntry",
    "StaleQueryExpiryEngine",
]
