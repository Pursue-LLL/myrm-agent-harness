"""Compile survey DTOs for vault-scoped structure scan before semantic extraction.

[INPUT]
- typing (POS: standard library type hints)

[OUTPUT]
- CompileSurveyContext: zero-LLM vault survey result for a compile session
- CompileSessionState: mutable session carrying facet seeds across worker batches
- FacetSurvey: folder-scoped facet metadata for one compile survey

[POS]
Wiki compile survey types. DTOs shared by survey builder and compiler orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAST_PATH_MAX_RAW_COUNT = 15
FAST_PATH_MAX_FOLDER_DEPTH = 1


@dataclass(frozen=True, slots=True)
class FacetSurvey:
    """Folder-scoped facet discovered during structure survey."""

    facet_id: str
    folder_path: str
    raw_paths: tuple[str, ...]
    suggested_seeds: tuple[str, ...]
    depth: int


@dataclass(frozen=True, slots=True)
class CompileSurveyContext:
    """Zero-LLM structure scan output for one compile session."""

    skipped: bool
    facet_count: int
    warning_count: int
    facets: dict[str, FacetSurvey]
    chunk_groups: dict[str, tuple[str, ...]]
    path_to_facet: dict[str, str]
    path_to_chunk_group: dict[str, str]
    processing_order: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class CompileSessionState:
    """Mutable compile session shared across worker batches for one vault."""

    context: CompileSurveyContext
    facet_seeds: dict[str, list[str]] = field(default_factory=dict)
