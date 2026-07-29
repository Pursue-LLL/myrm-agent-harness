"""Wiki apply service — vault lock + publish gate entrypoint.

[INPUT]
..handlers.apply_mutation_to_content (POS: narrow-write transforms)
..publication.publish_concept_article (POS: WPG publish SSOT)
..core.structure::WikiStructure (POS: vault paths)
..retrieval.indexer::WikiIndexer (POS: FTS/Qdrant upsert)

[OUTPUT]
apply_wiki_mutation: async publish orchestration with per-vault asyncio lock

[POS]
Single write orchestrator for REST, agent tool, and chat capture callers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    build_canonical_index,
    compute_page_lease_hash,
    find_canonical_conflict,
    stamp_content_hash,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import FrontmatterValidationError
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.apply.errors import WikiApplyError
from myrm_agent_harness.toolkits.wiki.pipeline.apply.handlers import apply_mutation_to_content
from myrm_agent_harness.toolkits.wiki.pipeline.apply.types import (
    WikiApplyCaller,
    WikiApplyOp,
    WikiApplyRequest,
    WikiApplyResult,
)
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

_VAULT_LOCKS: dict[str, asyncio.Lock] = {}
_SETTINGS_ONLY_OPS = frozenset({WikiApplyOp.REPLACE_FULL_DOCUMENT})


def _vault_lock(base_dir: Path) -> asyncio.Lock:
    key = str(base_dir.resolve())
    lock = _VAULT_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _VAULT_LOCKS[key] = lock
    return lock


def _read_existing_content(structure: WikiStructure, concept_name: str) -> str | None:
    path = structure.resolve_concept_file_path(concept_name)
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8")


async def apply_wiki_mutation(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    request: WikiApplyRequest,
    *,
    caller: WikiApplyCaller,
) -> WikiApplyResult:
    """Apply a narrow wiki mutation and publish through WPG."""
    if request.op in _SETTINGS_ONLY_OPS and caller != "settings":
        raise WikiApplyError(
            "forbidden_for_caller",
            "Full-document replace is settings-only; use narrow wiki apply operations.",
        )

    async with _vault_lock(structure.base_dir):
        canonical_index = build_canonical_index(structure)
        concept_name = request.concept_name.strip()

        if request.op == WikiApplyOp.CREATE_NOTE:
            conflict = find_canonical_conflict(
                canonical_index,
                concept_name=concept_name,
                canonical_id=request.canonical_id,
                aliases=request.aliases,
            )
            if conflict is not None:
                raise WikiApplyError(
                    "canonical_conflict",
                    f"Canonical identity already mapped to {conflict}",
                )

        if request.op == WikiApplyOp.UPDATE_METADATA and (
            request.aliases is not None or request.canonical_id is not None
        ):
            conflict = find_canonical_conflict(
                canonical_index,
                concept_name=concept_name,
                canonical_id=request.canonical_id,
                aliases=request.aliases,
            )
            if conflict is not None:
                raise WikiApplyError(
                    "canonical_conflict",
                    f"Canonical identity already mapped to {conflict}",
                )

        existing = None if request.op == WikiApplyOp.CREATE_NOTE else _read_existing_content(structure, concept_name)
        if existing is not None and request.if_match:
            current_hash = compute_page_lease_hash(existing)
            if request.if_match != current_hash:
                raise WikiApplyError(
                    "conflict",
                    "Page changed since it was loaded; refresh and retry.",
                )

        try:
            content, created, appended = apply_mutation_to_content(
                structure=structure,
                request=request,
                existing_content=existing,
                caller=caller,
            )
        except WikiApplyError:
            raise
        except ValueError as exc:
            raise WikiApplyError("invalid_request", str(exc)) from exc

        content = stamp_content_hash(content)

        try:
            await publish_concept_article(structure, indexer, concept_name, content)
        except FrontmatterValidationError as exc:
            raise WikiApplyError("invalid_frontmatter", "; ".join(exc.errors)) from exc

    return WikiApplyResult(
        success=True,
        op=request.op,
        concept_name=concept_name,
        message=f"Applied {request.op.value} to {concept_name}",
        created=created,
        appended=appended,
        content=content,
        content_hash=compute_page_lease_hash(content),
    )
