"""Ultra heuristic pre-filter for low-cost token pruning.

Performs deterministic, lightweight paragraph-level scoring and redundancy
filtering before transmitting long background documents to LLM or visual channels.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from .omniglyph_types import UltraFilterScore


class UltraHeuristicPreFilter:
    """Pre-filters high-volume background text using deterministic heuristics."""

    def __init__(
        self,
        min_density_threshold: float = 0.35,
        min_relevance_threshold: float = 0.20,
        min_combined_threshold: float = 0.40,
    ) -> None:
        self._min_density_threshold = min_density_threshold
        self._min_relevance_threshold = min_relevance_threshold
        self._min_combined_threshold = min_combined_threshold

    def filter_text(
        self,
        text: str,
        target_keywords: Sequence[str] = (),
    ) -> tuple[str, tuple[UltraFilterScore, ...]]:
        """Splits text into paragraphs, scores density and relevance, and filters noise."""
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not raw_paragraphs:
            return "", ()

        normalized_keywords = {kw.strip().lower() for kw in target_keywords if kw.strip()}
        scores: list[UltraFilterScore] = []
        retained_paragraphs: list[str] = []

        seen_fingerprints: set[str] = set()

        for idx, para in enumerate(raw_paragraphs):
            seg_id = f"seg_{idx:04d}"
            fingerprint = self._compute_fingerprint(para)

            # Detect verbatim duplicate paragraphs
            if fingerprint in seen_fingerprints:
                scores.append(
                    UltraFilterScore(
                        segment_id=seg_id,
                        original_text=para,
                        information_density=0.0,
                        relevance_score=0.0,
                        combined_score=0.0,
                        keep_decision=False,
                        reason="duplicate_verbatim_paragraph",
                    )
                )
                continue
            seen_fingerprints.add(fingerprint)

            density = self._calculate_information_density(para)
            relevance = self._calculate_relevance(para, normalized_keywords)

            # Combined score: 60% density + 40% relevance (or 100% density if no keywords)
            if normalized_keywords:
                combined = 0.6 * density + 0.4 * relevance
            else:
                combined = density

            # Boilerplate detection (e.g. standard disclaimers, cookie notices)
            is_boilerplate = self._is_boilerplate(para)
            if is_boilerplate:
                scores.append(
                    UltraFilterScore(
                        segment_id=seg_id,
                        original_text=para,
                        information_density=density,
                        relevance_score=relevance,
                        combined_score=combined,
                        keep_decision=False,
                        reason="detected_boilerplate_or_disclaimer",
                    )
                )
                continue

            keep = combined >= self._min_combined_threshold
            reason = "passed_heuristic_threshold" if keep else "low_information_or_relevance"

            scores.append(
                UltraFilterScore(
                    segment_id=seg_id,
                    original_text=para,
                    information_density=round(density, 4),
                    relevance_score=round(relevance, 4),
                    combined_score=round(combined, 4),
                    keep_decision=keep,
                    reason=reason,
                )
            )

            if keep:
                retained_paragraphs.append(para)

        filtered_text = "\n\n".join(retained_paragraphs)
        return filtered_text, tuple(scores)

    def _calculate_information_density(self, text: str) -> float:
        """Measures lexical variety and entropy of the text segment."""
        tokens = [t.lower() for t in re.findall(r"\w+", text)]
        if not tokens:
            return 0.0

        total_words = len(tokens)
        unique_words = len(set(tokens))
        ttr = unique_words / total_words  # Type-Token Ratio

        # Penalize extremely short trivial segments
        if total_words < 5:
            return round(ttr * 0.4, 4)

        # Character entropy estimation
        char_counts: dict[str, int] = {}
        for char in text:
            char_counts[char] = char_counts.get(char, 0) + 1
        total_chars = len(text)
        entropy = 0.0
        for count in char_counts.values():
            p = count / total_chars
            entropy -= p * math.log2(p)

        # Normalize entropy (typical English text has entropy between 3.5 and 4.8)
        norm_entropy = min(1.0, max(0.0, entropy / 5.0))

        # Balanced density score
        return round(0.5 * ttr + 0.5 * norm_entropy, 4)

    def _calculate_relevance(self, text: str, keywords: set[str]) -> float:
        """Calculates keyword presence and density in the segment."""
        if not keywords:
            return 1.0  # If no keywords specified, treat all segments as relevant

        lower_text = text.lower()
        matched = 0
        for kw in keywords:
            if kw in lower_text:
                matched += 1

        match_ratio = matched / len(keywords)
        return round(min(1.0, match_ratio * 1.5), 4)

    def _compute_fingerprint(self, text: str) -> str:
        """Produces normalized whitespace fingerprint for dedup."""
        return re.sub(r"\s+", " ", text).strip().lower()

    def _is_boilerplate(self, text: str) -> bool:
        """Heuristically identifies generic boilerplate, footer, and privacy notices."""
        lower = text.lower()
        boilerplate_cues = (
            "all rights reserved",
            "terms of service",
            "privacy policy",
            "copyright ©",
            "this email was sent to",
            "unsubscribe from this list",
            "cookie policy",
            "disclaimer: the information contained",
        )
        return any(cue in lower for cue in boilerplate_cues)
