"""CCSP orchestration service.

[INPUT]
..pipeline.pending::WikiPendingEditsManager (POS: stage evolution drafts)
..core.types::ConceptInfo (POS: compile batch concepts)

[OUTPUT]
- run_contradiction_synthesis_pass

[POS]
Compile Step 2.5 — cross-concept evolution page synthesis after article generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .detector import detect_conflict
from .pairing import collect_concept_pairs
from .types import SynthesisPassResult
from .writer import build_synthesis_page

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


async def run_contradiction_synthesis_pass(
    llm: BaseChatModel,
    structure: WikiStructure,
    compile_config: WikiCompileConfig,
    indexer: WikiIndexer | None,
    batch_concepts: list[ConceptInfo],
) -> SynthesisPassResult:
    """Detect cross-concept conflicts and stage evolution synthesis pages."""
    _ = compile_config
    filtered = [concept for concept in batch_concepts if concept.name.strip()]
    pairs = collect_concept_pairs(filtered, structure)
    if not pairs:
        return SynthesisPassResult(pairs_considered=0, synthesis_staged=0)

    definitions = {concept.name: concept.definition for concept in filtered}
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WikiProvenance
    from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager

    pending_mgr = WikiPendingEditsManager(structure, indexer)
    staged = 0

    for pair in pairs:
        verdict = await detect_conflict(
            llm,
            structure,
            pair,
            definition_a=definitions.get(pair.concept_a, ""),
            definition_b=definitions.get(pair.concept_b, ""),
        )
        if verdict is None:
            continue
        concept_path, page_content = build_synthesis_page(verdict, pair)
        await pending_mgr.stage_pending_edit(
            concept_path,
            page_content,
            source_files=[pair.concept_a, pair.concept_b],
            provenance=WikiProvenance.CONTRADICTION_SYNTHESIS,
        )
        staged += 1
        logger.info(
            "Staged evolution synthesis %s for %s vs %s",
            concept_path,
            pair.concept_a,
            pair.concept_b,
        )

    return SynthesisPassResult(pairs_considered=len(pairs), synthesis_staged=staged)
