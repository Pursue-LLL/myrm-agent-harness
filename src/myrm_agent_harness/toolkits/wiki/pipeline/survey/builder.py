"""Zero-LLM compile structure survey for wiki vault raw files.

[INPUT]
..core.structure::WikiStructure (POS: vault filesystem layout)
.types::CompileSurveyContext, FacetSurvey, FAST_PATH_* (POS: survey DTOs and thresholds)

[OUTPUT]
build_compile_survey: Build folder facets, chunk sibling groups, and processing order

[POS]
Pre-semantic compile survey. Groups pending raw paths by folder facet, detects
`_chunkNNN` siblings, and skips survey for small shallow vaults (fast-path).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path, PurePosixPath

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

from .types import (
    FAST_PATH_MAX_FOLDER_DEPTH,
    FAST_PATH_MAX_RAW_COUNT,
    CompileSurveyContext,
    FacetSurvey,
)

_CHUNK_SUFFIX = re.compile(r"_chunk\d+$", re.IGNORECASE)


def _relative_posix(base_dir: Path, raw_path: Path) -> str:
    try:
        return raw_path.relative_to(base_dir).as_posix()
    except ValueError:
        return raw_path.name


def _folder_depth(relative_path: str) -> int:
    parent = PurePosixPath(relative_path).parent
    if str(parent) in {"", "."}:
        return 0
    return len(parent.parts)


def _facet_folder(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent
    if str(parent) in {"", "."}:
        return "."
    return parent.as_posix()


def _path_stem(relative_path: str) -> str:
    return PurePosixPath(relative_path).stem


def _chunk_group_key(relative_path: str) -> str | None:
    stem = _path_stem(relative_path)
    if not _CHUNK_SUFFIX.search(stem):
        return None
    base_stem = _CHUNK_SUFFIX.sub("", stem)
    parent = _facet_folder(relative_path)
    return f"{parent}/{base_stem}" if parent != "." else base_stem


def _suggested_seed(relative_path: str) -> str:
    folder = _facet_folder(relative_path)
    stem = _path_stem(relative_path)
    base_stem = _CHUNK_SUFFIX.sub("", stem)
    if folder == ".":
        return base_stem.replace("-", " ").title()
    folder_title = "/".join(part.replace("-", " ").title() for part in folder.split("/"))
    return f"{folder_title}/{base_stem.replace('-', ' ').title()}"


def _empty_context(*, skipped: bool) -> CompileSurveyContext:
    return CompileSurveyContext(
        skipped=skipped,
        facet_count=0,
        warning_count=0,
        facets={},
        chunk_groups={},
        path_to_facet={},
        path_to_chunk_group={},
        processing_order=(),
        warnings=(),
    )


def build_compile_survey(
    structure: WikiStructure,
    raw_paths: list[Path],
    *,
    fast_path_scope_paths: list[Path] | None = None,
) -> CompileSurveyContext:
    """Build a compile survey for the given pending raw file paths."""
    if not raw_paths:
        return _empty_context(skipped=True)

    rel_paths = [_relative_posix(structure.base_dir, path) for path in raw_paths]
    scope_paths = fast_path_scope_paths if fast_path_scope_paths is not None else raw_paths
    scope_rel_paths = [_relative_posix(structure.base_dir, path) for path in scope_paths]
    if scope_rel_paths:
        scope_max_depth = max(_folder_depth(rel) for rel in scope_rel_paths)
        if len(scope_rel_paths) <= FAST_PATH_MAX_RAW_COUNT and scope_max_depth <= FAST_PATH_MAX_FOLDER_DEPTH:
            return _empty_context(skipped=True)

    facet_paths: dict[str, list[str]] = defaultdict(list)
    for rel in rel_paths:
        facet_paths[_facet_folder(rel)].append(rel)

    chunk_groups: dict[str, list[str]] = defaultdict(list)
    path_to_chunk_group: dict[str, str] = {}
    for rel in rel_paths:
        group_key = _chunk_group_key(rel)
        if group_key is None:
            continue
        chunk_groups[group_key].append(rel)
        path_to_chunk_group[rel] = group_key

    warnings: list[str] = []
    for group_key, members in chunk_groups.items():
        if len(members) > 1:
            warnings.append(f"chunk_group:{group_key}:{len(members)}")

    facets: dict[str, FacetSurvey] = {}
    path_to_facet: dict[str, str] = {}
    for folder, paths in facet_paths.items():
        sorted_paths = tuple(sorted(paths))
        facet_id = folder
        seeds = tuple(dict.fromkeys(_suggested_seed(path) for path in sorted_paths[:8]))
        depth = _folder_depth(sorted_paths[0])
        facets[facet_id] = FacetSurvey(
            facet_id=facet_id,
            folder_path=folder,
            raw_paths=sorted_paths,
            suggested_seeds=seeds,
            depth=depth,
        )
        for rel in sorted_paths:
            path_to_facet[rel] = facet_id

    processing_order = tuple(
        facet_id
        for facet_id, _facet in sorted(
            facets.items(),
            key=lambda item: (item[1].depth, item[1].folder_path),
        )
    )

    frozen_chunk_groups = {key: tuple(sorted(values)) for key, values in chunk_groups.items()}

    return CompileSurveyContext(
        skipped=False,
        facet_count=len(facets),
        warning_count=len(warnings),
        facets=facets,
        chunk_groups=frozen_chunk_groups,
        path_to_facet=path_to_facet,
        path_to_chunk_group=path_to_chunk_group,
        processing_order=processing_order,
        warnings=tuple(warnings),
    )
