"""Memory Defense Ingestion Firewall and PII Sanitization Suite."""

from __future__ import annotations

from .defense_firewall import MemoryDefenseFirewall
from .pattern_catalog import (
    CompiledPattern,
    get_builtin_patterns,
    get_compiled_patterns,
)
from .types import (
    DefenseAction,
    DefensePolicy,
    DetectionMatch,
    MemoryDefenseResult,
    PatternSpec,
    SensitiveCategory,
)

__all__ = [
    "CompiledPattern",
    "DefenseAction",
    "DefensePolicy",
    "DetectionMatch",
    "MemoryDefenseFirewall",
    "MemoryDefenseResult",
    "PatternSpec",
    "SensitiveCategory",
    "get_builtin_patterns",
    "get_compiled_patterns",
]
