"""Persona semantic conflict probe and mutual exclusion resolver.

[INPUT]
- runtime.context.persona_conflict_resolver_types::ArbitratedPersonaResult, PersonaConflictFinding,
  PersonaSnippet, PersonaSourceTier, PolarityDimension (POS: Data contracts and types for persona semantic
  conflict probe and mutual exclusion resolver.)

[OUTPUT]
- PolarityPatternRegistry: Registry of antagonistic keywords and phrases across semantic polarity
  dimensions.
- PersonaSemanticConflictProbe: Scans persona snippets to detect semantic clashes and mutually exclusive
  directives.
- PersonaMutualExclusionResolver: Arbitrates detected persona conflicts by enforcing hard custom/session
  overrides.

[POS]
Persona semantic conflict probe and mutual exclusion resolver.
"""

from __future__ import annotations

from threading import RLock
from typing import ClassVar

from myrm_agent_harness.runtime.context.persona_conflict_resolver_types import (
    ArbitratedPersonaResult,
    PersonaConflictFinding,
    PersonaSnippet,
    PersonaSourceTier,
    PolarityDimension,
)


class PolarityPatternRegistry:
    """Registry of antagonistic keywords and phrases across semantic polarity dimensions."""

    _PATTERNS: ClassVar[dict[PolarityDimension, tuple[tuple[str, ...], tuple[str, ...]]]] = {
        PolarityDimension.GENTLE_VS_BLUNT: (
            ("温柔", "可爱", "萌萌哒", "sweet", "gentle", "cute", "soft", "亲切", "贴心", "顺从"),
            ("暴躁", "大老粗", "硬核", "毒舌", "blunt", "harsh", "sarcastic", "rough", "直言不讳", "冷酷"),
        ),
        PolarityDimension.VERBOSITY_VS_TERSE: (
            ("详细展开", "详尽阐述", "多角度解释", "elaborate", "verbose", "comprehensive explanation", "细致论述"),
            ("极简", "一句话回答", "绝不多说", "caveman", "terse", "ultra-compact", "极短", "砍掉解释", "无废话"),
        ),
        PolarityDimension.SUBMISSIVE_VS_OPINIONATED: (
            ("盲从", "完全听从", "毫无主见", "sycophantic", "submissive", "用户说什么就是什么", "无限附和"),
            ("有主见", "敢于质疑", "坚持原则", "have opinions", "opinionated", "critical thinking", "主动反驳"),
        ),
        PolarityDimension.FORMAL_VS_CASUAL: (
            ("阁下", "谨遵", "极其庄重", "formal", "honorific", "ceremonial", "敬启者", "书面学术"),
            ("大白话", "唠嗑", "口语化", "slang", "street", "casual", "随意唠嗑", "随性"),
        ),
    }

    @classmethod
    def match_polarities(
        cls, text: str
    ) -> dict[PolarityDimension, tuple[str, list[str]]]:
        """Detects whether text aligns with Side A or Side B of each polarity dimension."""
        lower = text.lower()
        matched: dict[PolarityDimension, tuple[str, list[str]]] = {}

        for dimension, (side_a, side_b) in cls._PATTERNS.items():
            hits_a = [kw for kw in side_a if kw.lower() in lower]
            hits_b = [kw for kw in side_b if kw.lower() in lower]

            if hits_a and not hits_b:
                matched[dimension] = ("A", hits_a)
            elif hits_b and not hits_a:
                matched[dimension] = ("B", hits_b)
            elif hits_a and hits_b:
                # Internal contradiction within single snippet: favor the one with more keyword density
                if len(hits_b) >= len(hits_a):
                    matched[dimension] = ("B", hits_b)
                else:
                    matched[dimension] = ("A", hits_a)

        return matched


class PersonaSemanticConflictProbe:
    """Scans persona snippets to detect semantic clashes and mutually exclusive directives."""

    @classmethod
    def scan_conflicts(
        cls, snippets: list[PersonaSnippet]
    ) -> list[PersonaConflictFinding]:
        """Analyzes pairs of persona snippets for antagonistic polarity opposition."""
        findings: list[PersonaConflictFinding] = []
        n = len(snippets)

        for i in range(n):
            snip_a = snippets[i]
            pols_a = PolarityPatternRegistry.match_polarities(snip_a.content)

            for j in range(i + 1, n):
                snip_b = snippets[j]
                pols_b = PolarityPatternRegistry.match_polarities(snip_b.content)

                for dim, (side_a, hits_a) in pols_a.items():
                    if dim in pols_b:
                        side_b, hits_b = pols_b[dim]
                        if side_a != side_b:
                            # Direct clash on polarity dimension
                            if snip_a.priority_weight >= snip_b.priority_weight:
                                dom, sub = snip_a, snip_b
                                dom_hits, sub_hits = hits_a, hits_b
                            else:
                                dom, sub = snip_b, snip_a
                                dom_hits, sub_hits = hits_b, hits_a

                            findings.append(
                                PersonaConflictFinding(
                                    dimension=dim,
                                    dominant_snippet=dom,
                                    subordinate_snippet=sub,
                                    conflicting_keywords_dominant=tuple(dom_hits),
                                    conflicting_keywords_subordinate=tuple(sub_hits),
                                    explanation=(
                                        f"Conflict on {dim}: dominant '{dom.snippet_id}' (tier={dom.source_tier}) "
                                        f"clashes with subordinate '{sub.snippet_id}' (tier={sub.source_tier})."
                                    ),
                                )
                            )

        return findings


class PersonaMutualExclusionResolver:
    """Arbitrates detected persona conflicts by enforcing hard custom/session overrides."""

    def __init__(self) -> None:
        self._lock = RLock()

    def resolve_conflicts(
        self,
        snippets: list[PersonaSnippet],
    ) -> ArbitratedPersonaResult:
        """Arbitrates antagonistic persona snippets, dropping subordinated ones to yield unity."""
        with self._lock:
            conflicts = PersonaSemanticConflictProbe.scan_conflicts(snippets)
            dropped_ids = {c.subordinate_snippet.snippet_id for c in conflicts}

            retained: list[PersonaSnippet] = []
            dropped: list[PersonaSnippet] = []

            for snip in snippets:
                if snip.snippet_id in dropped_ids:
                    dropped.append(snip)
                else:
                    retained.append(snip)

            unified_text = "\n\n".join(s.content.strip() for s in retained if s.content.strip())
            is_conflict_free = len(conflicts) == 0

            return ArbitratedPersonaResult(
                resolved_persona_text=unified_text,
                retained_snippets=tuple(retained),
                dropped_conflicting_snippets=tuple(dropped),
                conflicts_detected=tuple(conflicts),
                is_conflict_free=is_conflict_free,
            )

    @staticmethod
    def create_snippet(
        snippet_id: str,
        content: str,
        tier: PersonaSourceTier = PersonaSourceTier.USER_CUSTOM,
        explicit_priority: int | None = None,
    ) -> PersonaSnippet:
        """Factory helper with standard tier-based priority weights."""
        tier_weights = {
            PersonaSourceTier.SYSTEM_DEFAULT: 10,
            PersonaSourceTier.WORKSPACE_RULE: 50,
            PersonaSourceTier.USER_CUSTOM: 100,
            PersonaSourceTier.SESSION_OVERRIDE: 200,
        }
        weight = explicit_priority if explicit_priority is not None else tier_weights.get(tier, 10)
        return PersonaSnippet(
            snippet_id=snippet_id,
            source_tier=tier,
            content=content.strip(),
            priority_weight=weight,
        )
