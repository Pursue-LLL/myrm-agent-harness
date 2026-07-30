"""Evolution synthesis page writer for CCSP.

[INPUT]
..core.frontmatter_contract (POS: page type + metadata)
..core.section_contract (POS: Compiled Truth / Timeline skeleton)
..core.claims_contract (POS: contested claims)

[OUTPUT]
- build_evolution_concept_path, build_synthesis_page

[POS]
Build pending comparison/evolution wiki pages after conflict detection.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.wiki.core.claims_contract import WikiClaim, WikiEvidence, merge_claims_into_content
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WikiPageType,
    ensure_frontmatter_type,
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.section_contract import build_note_body_skeleton

from .types import ConceptPair, ConflictVerdict

_SYNTHESIS_KIND = "evolution"
_LINKED_CONCEPTS_KEY = "linked_concepts"


def _topic_has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _slugify_topic(topic: str) -> str:
    cleaned = topic.strip().replace("\\", "/")
    cleaned = re.sub(r"[^\w\s\-/]", "", cleaned, flags=re.UNICODE)
    cleaned = cleaned.replace(" ", "-")
    parts = [segment for segment in cleaned.split("/") if segment]
    if not parts:
        return "topic"
    return "/".join(parts[:3])


def build_evolution_concept_path(topic: str) -> str:
    """Deterministic evolution page path under Comparisons/."""
    slug = _slugify_topic(topic)
    return f"Comparisons/{slug}/Evolution"


def _build_compiled_truth_section(
    verdict: ConflictVerdict,
    pair: ConceptPair,
    *,
    title_suffix: str,
    link_a: str,
    link_b: str,
) -> str:
    if _topic_has_cjk(verdict.topic):
        return (
            f"### {title_suffix}\n\n"
            f"本页记录 {link_a} 与 {link_b} 之间的事实冲突。\n\n"
            f"| 立场 | 摘要 |\n| --- | --- |\n"
            f"| {link_a} | {verdict.side_a} |\n"
            f"| {link_b} | {verdict.side_b} |\n\n"
            f"**建议下一步：** {verdict.resolution_hint}"
        )
    return (
        f"### {title_suffix}\n\n"
        f"This page tracks a factual conflict between {link_a} and {link_b}.\n\n"
        f"| Position | Summary |\n| --- | --- |\n"
        f"| {link_a} | {verdict.side_a} |\n"
        f"| {link_b} | {verdict.side_b} |\n\n"
        f"**Suggested next step:** {verdict.resolution_hint}"
    )


def _build_timeline_entry(
    verdict: ConflictVerdict,
    pair: ConceptPair,
    *,
    link_a: str,
    link_b: str,
) -> str:
    if _topic_has_cjk(verdict.topic):
        return (
            f"编译批次合成待审（{pair.reason}）：{link_a} vs {link_b} "
            f"（置信度 {verdict.confidence:.2f}）。"
        )
    return (
        f"Synthesis staged from compile batch ({pair.reason}): {link_a} vs {link_b} "
        f"(confidence {verdict.confidence:.2f})."
    )


def build_synthesis_page(
    verdict: ConflictVerdict,
    pair: ConceptPair,
) -> tuple[str, str]:
    """Return (concept_path, markdown_content) for a pending evolution page."""
    concept_path = build_evolution_concept_path(verdict.topic)
    link_a = f"[[{pair.concept_a}]]"
    link_b = f"[[{pair.concept_b}]]"
    title_suffix = f"{verdict.topic}的演变" if _topic_has_cjk(verdict.topic) else f"Evolution of {verdict.topic}"

    compiled_truth = _build_compiled_truth_section(
        verdict,
        pair,
        title_suffix=title_suffix,
        link_a=link_a,
        link_b=link_b,
    )
    timeline_entry = _build_timeline_entry(verdict, pair, link_a=link_a, link_b=link_b)
    body = build_note_body_skeleton(compiled_truth=compiled_truth, timeline_entry=timeline_entry)
    content = ensure_frontmatter_type(
        body,
        WikiPageType.COMPARISON,
        sources=[pair.concept_a, pair.concept_b],
        provenance="contradiction_synthesis",
    )
    metadata, body_only = load_frontmatter_metadata(content)
    metadata["synthesis_kind"] = _SYNTHESIS_KIND
    metadata[_LINKED_CONCEPTS_KEY] = [pair.concept_a, pair.concept_b]
    metadata["tags"] = ["conflict-synthesis", "evolution"]
    content = serialize_frontmatter_block(metadata) + body_only.lstrip("\n")

    slug = concept_path.replace("/", ".").lower()
    claims = (
        WikiClaim(
            id=f"claim.{slug}.position-a",
            text=verdict.side_a,
            status="contested",
            confidence=verdict.confidence,
            evidence=(
                WikiEvidence(
                    kind="concept-link",
                    source_id=f"concept.{slug}.a",
                    path=pair.concept_a,
                    lines="",
                    weight=1.0,
                    confidence=verdict.confidence,
                    note="Position A",
                ),
            ),
        ),
        WikiClaim(
            id=f"claim.{slug}.position-b",
            text=verdict.side_b,
            status="contested",
            confidence=verdict.confidence,
            evidence=(
                WikiEvidence(
                    kind="concept-link",
                    source_id=f"concept.{slug}.b",
                    path=pair.concept_b,
                    lines="",
                    weight=1.0,
                    confidence=verdict.confidence,
                    note="Position B",
                ),
            ),
        ),
    )
    content = merge_claims_into_content(content, claims)
    return concept_path, content


def synthesis_page_uses_cjk_body(content: str) -> bool:
    """Return True when evolution page body uses the CJK compile template."""
    return "本页记录" in content


def parse_synthesis_backlink_targets(content: str) -> tuple[str, ...]:
    """Return linked concept paths when content is an approved evolution synthesis page."""
    metadata, _ = load_frontmatter_metadata(content)
    if str(metadata.get("synthesis_kind", "")).strip() != _SYNTHESIS_KIND:
        return ()
    linked = metadata.get(_LINKED_CONCEPTS_KEY)
    if not isinstance(linked, list):
        return ()
    cleaned = tuple(str(item).strip() for item in linked if str(item).strip())
    return cleaned
