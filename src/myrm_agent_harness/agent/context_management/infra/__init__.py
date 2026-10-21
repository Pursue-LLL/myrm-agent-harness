"""Context management infrastructure: shared types, budget management, session locks, and optional cache metrics persistence."""

from .compactor_guard import CompactorPreflightFence, CompactorSafetyVerdict

__all__ = [
    "CompactorPreflightFence",
    "CompactorSafetyVerdict",
]
