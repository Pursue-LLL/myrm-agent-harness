"""Rebuild wiki vectors after embedding model or chunking policy changes.

[INPUT]
..core.structure::WikiStructure (POS: vault paths)
..retrieval.indexer::WikiIndexer (POS: FTS/Qdrant upsert + sidecar mixin)
..retrieval.asset_index::WikiAssetIndexer (POS: optional asset caption vectors)

[OUTPUT]
WikiVectorReindexResult, reindex_published_vectors()

[POS]
Harness wiki vector reindex SSOT. Re-embeds published L2 concepts, L0/L1 directory
sidecars, and optional wiki/assets captions using the active embedding window policy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError

from ..core.frontmatter_contract import WikiPublishStatus
from ..core.structure import WikiStructure
from .indexer import WikiIndexer

if TYPE_CHECKING:
    from .asset_index import WikiAssetIndexer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WikiVectorReindexResult:
    concepts_scanned: int
    concepts_reindexed: int
    skipped_drafts: int
    sidecars_reindexed: int
    assets_indexed: int
    assets_failed: int
    failed: int
    errors: tuple[str, ...]

    @property
    def scanned(self) -> int:
        return self.concepts_scanned

    @property
    def reindexed(self) -> int:
        return self.concepts_reindexed + self.sidecars_reindexed + self.assets_indexed


def _iter_sidecar_files(structure: WikiStructure) -> list[tuple[str, int, Path]]:
    """Yield (dir_path, level, path) for on-disk L0/L1 sidecar markdown files."""
    entries: list[tuple[str, int, Path]] = []
    if not structure.concepts_dir.is_dir():
        return entries

    for path in sorted(structure.concepts_dir.rglob("*.md")):
        if path.name == structure.DIRECTORY_ABSTRACT_FILENAME:
            level = 0
        elif path.name == structure.DIRECTORY_OVERVIEW_FILENAME:
            level = 1
        else:
            continue
        rel_dir = path.parent.relative_to(structure.concepts_dir)
        dir_path = "" if str(rel_dir) == "." else str(rel_dir).replace("\\", "/")
        entries.append((dir_path, level, path))
    return entries


async def reindex_published_vectors(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    *,
    asset_indexer: WikiAssetIndexer | None = None,
) -> WikiVectorReindexResult:
    """Re-upsert published concept, sidecar, and optional asset vectors."""
    if indexer is None:
        indexer = WikiIndexer(structure)

    concepts_scanned = 0
    concepts_reindexed = 0
    skipped_drafts = 0
    sidecars_reindexed = 0
    assets_indexed = 0
    assets_failed = 0
    failed = 0
    errors: list[str] = []

    for concept_path in structure.list_concepts():
        try:
            rel = str(concept_path.relative_to(structure.concepts_dir).with_suffix("")).replace("\\", "/")
        except ValueError:
            # Federated public mounts are read-only; local vault reindex only.
            continue

        concepts_scanned += 1
        try:
            content = concept_path.read_text(encoding="utf-8")
            publish_status = WikiIndexer._resolve_publish_status(content)
            if publish_status != WikiPublishStatus.PUBLISHED.value:
                skipped_drafts += 1
                continue

            await indexer.upsert(rel, content)
            edge_result = indexer.extract_and_upsert_edges(rel, content)
            if hasattr(edge_result, "__await__"):
                await edge_result
            concepts_reindexed += 1
        except EmbedInputTooLargeError as exc:
            failed += 1
            errors.append(f"concept:{rel}: {exc}")
        except OSError as exc:
            failed += 1
            errors.append(f"concept:{concept_path}: {exc}")
        except Exception as exc:
            failed += 1
            errors.append(f"concept:{rel}: {exc}")
            logger.error("Wiki concept vector reindex failed for %s: %s", rel, exc)

    if indexer._config.enable_directory_sidecars:
        for dir_path, level, sidecar_path in _iter_sidecar_files(structure):
            label = f"sidecar:L{level}:{dir_path or 'root'}"
            try:
                content = sidecar_path.read_text(encoding="utf-8")
                await indexer.upsert_sidecar(dir_path, level=level, content=content)
                sidecars_reindexed += 1
            except EmbedInputTooLargeError as exc:
                failed += 1
                errors.append(f"{label}: {exc}")
            except OSError as exc:
                failed += 1
                errors.append(f"{label}:{sidecar_path}: {exc}")
            except Exception as exc:
                failed += 1
                errors.append(f"{label}: {exc}")
                logger.error("Wiki sidecar vector reindex failed for %s: %s", label, exc)

    if asset_indexer is not None and indexer._config.enable_asset_index:
        try:
            asset_result = await asset_indexer.index_all()
            assets_indexed = asset_result.indexed
            assets_failed = asset_result.failed
            if asset_result.failed:
                failed += asset_result.failed
                errors.append(f"assets: {asset_result.failed} caption index failure(s)")
        except Exception as exc:
            failed += 1
            errors.append(f"assets: {exc}")
            logger.error("Wiki asset vector reindex failed: %s", exc)

    return WikiVectorReindexResult(
        concepts_scanned=concepts_scanned,
        concepts_reindexed=concepts_reindexed,
        skipped_drafts=skipped_drafts,
        sidecars_reindexed=sidecars_reindexed,
        assets_indexed=assets_indexed,
        assets_failed=assets_failed,
        failed=failed,
        errors=tuple(errors),
    )
