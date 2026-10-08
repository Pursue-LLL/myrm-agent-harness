"""Scoped CSS Isolation and Parallel Micro-Agent Boundary Sentinel Module.

Provides AST-level CSS scoping, prohibition of global root selectors (body, html, :root, *),
and concurrent multi-agent style patch collision detection.
"""

from __future__ import annotations

from .conflict_detector import ConcurrentStyleConflictDetector
from .css_rewriter import ScopedCssAstRewriter
from .types import (
    ConcurrentStylePatch,
    ConflictCheckResult,
    CssScopingResult,
    CssViolationSeverity,
    GlobalSelectorViolation,
)

__all__ = [
    "ConcurrentStyleConflictDetector",
    "ConcurrentStylePatch",
    "ConflictCheckResult",
    "CssScopingResult",
    "CssViolationSeverity",
    "GlobalSelectorViolation",
    "ScopedCssAstRewriter",
]
