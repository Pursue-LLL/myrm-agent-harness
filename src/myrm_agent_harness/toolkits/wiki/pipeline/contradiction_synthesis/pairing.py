"""Zero-LLM concept pairing for CCSP.

[INPUT]
..core.types::ConceptInfo (POS: batch concepts from compiler)
..core.canonical_registry (POS: vault canonical index)
..core.structure::WikiStructure (POS: vault paths)

[OUTPUT]
- collect_concept_pairs: ranked distinct concept pairs for conflict detection

[POS]
Prefilter cross-concept conflicts before optional LLM verdict. Skips same-name merged concepts.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    build_canonical_index,
    derive_canonical_id,
    normalize_registry_key,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

from .types import ConceptPair

MAX_PAIR_CANDIDATES = 3


def _tail_slug(concept_name: str) -> str:
    cleaned = concept_name.strip().replace("\\", "/")
    tail = cleaned.rsplit("/", maxsplit=1)[-1]
    return normalize_registry_key(tail)


def _pair_key(concept_a: str, concept_b: str) -> tuple[str, str]:
    ordered = sorted((concept_a, concept_b))
    return ordered[0], ordered[1]


def collect_concept_pairs(
    batch_concepts: list[ConceptInfo],
    structure: WikiStructure,
    *,
    max_pairs: int = MAX_PAIR_CANDIDATES,
) -> list[ConceptPair]:
    """Collect up to ``max_pairs`` distinct cross-concept pairs from a compile batch."""
    if len(batch_concepts) < 2:
        return []

    canonical_index = build_canonical_index(structure)
    batch_by_name = {concept.name: concept for concept in batch_concepts}

    scored: dict[tuple[str, str], tuple[int, ConceptPair]] = {}

    def _register(concept_a: str, concept_b: str, reason: str, score: int) -> None:
        if concept_a == concept_b:
            return
        key = _pair_key(concept_a, concept_b)
        existing = scored.get(key)
        if existing is not None and existing[0] >= score:
            return
        scored[key] = (score, ConceptPair(concept_a=concept_a, concept_b=concept_b, reason=reason))

    concept_names = list(batch_by_name.keys())
    for left_index, concept_a in enumerate(concept_names):
        info_a = batch_by_name[concept_a]
        canonical_a = derive_canonical_id(concept_a)
        slug_a = _tail_slug(concept_a)
        for concept_b in concept_names[left_index + 1 :]:
            info_b = batch_by_name[concept_b]
            if concept_a in info_b.related_concepts or concept_b in info_a.related_concepts:
                _register(concept_a, concept_b, "related_concept", 3)
                continue
            canonical_b = derive_canonical_id(concept_b)
            if canonical_a == canonical_b:
                _register(concept_a, concept_b, "canonical_id", 2)
                continue
            if slug_a and slug_a == _tail_slug(concept_b):
                _register(concept_a, concept_b, "shared_slug", 1)

    for concept in batch_concepts:
        canonical_id = derive_canonical_id(concept.name)
        existing_name = canonical_index.by_canonical_id.get(normalize_registry_key(canonical_id))
        if existing_name and existing_name != concept.name:
            _register(concept.name, existing_name, "vault_canonical", 4)

    ordered = sorted(
        (pair for _, pair in scored.values()),
        key=lambda pair: (
            0 if pair.reason == "vault_canonical" else 1 if pair.reason == "related_concept" else 2,
            pair.concept_a,
            pair.concept_b,
        ),
    )
    return ordered[: max(0, max_pairs)]
