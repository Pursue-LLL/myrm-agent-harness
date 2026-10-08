"""Codebase memory large diff fallback toolkit.

Provides adaptive multi-tiered diff volume fallback (Micro, Moderate, Large, Massive),
noise file filtering, API truncation guards, and safe topological summarization.
"""

from __future__ import annotations

from .classifier import DiffPathClassifier
from .facade import CodebaseDiffFallbackSuite
from .models import (
    DiffCategory,
    DiffFallbackVerdict,
    DiffFileEntry,
    DiffVolumeTier,
    DirectoryAggregate,
    LargeDiffFallbackConfig,
)
from .pipeline import LargeDiffFallbackPipeline

__all__ = [
    "CodebaseDiffFallbackSuite",
    "DiffCategory",
    "DiffFallbackVerdict",
    "DiffFileEntry",
    "DiffPathClassifier",
    "DiffVolumeTier",
    "DirectoryAggregate",
    "LargeDiffFallbackConfig",
    "LargeDiffFallbackPipeline",
]
