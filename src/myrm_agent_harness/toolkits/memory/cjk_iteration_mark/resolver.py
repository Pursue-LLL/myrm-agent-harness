"""Resolver for CJK ideographic iteration mark disambiguation and tokenization.

Implements chained antecedent resolution for U+3005 ('々'), ensuring iteration marks
repeat only immediately preceding Han characters in the same contiguous run, while
generating raw, normalized, and contextual anchor bigram matrices.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.models import (
    DisambiguatedCjkTokens,
    IterationExpansionResult,
    IterationMarkRun,
)


class IterationMarkResolver:
    """Disambiguates CJK iteration marks ('々') and generates three-dimensional tokens."""

    ITERATION_MARK: ClassVar[str] = "\u3005"  # '々'
    _LATIN_WORD_RE: ClassVar[re.Pattern[str]] = re.compile(r"[a-zA-Z0-9_-]+")

    def resolve(self, text: str) -> IterationExpansionResult:
        """Resolve iteration marks across entire input text and extract token matrices."""
        if not text:
            return IterationExpansionResult(
                original_text="",
                normalized_text="",
                has_iteration_mark=False,
                marks_expanded_count=0,
                runs=(),
                tokens=DisambiguatedCjkTokens(),
            )

        runs: list[IterationMarkRun] = []
        normalized_segments: list[str] = []
        cjk_buffer: list[str] = []
        marks_expanded_total = 0

        def flush_cjk_buffer() -> None:
            nonlocal marks_expanded_total
            if not cjk_buffer:
                return

            raw_cjk = "".join(cjk_buffer)
            run_obj, expanded_count = self._expand_single_cjk_run(raw_cjk)
            marks_expanded_total += expanded_count
            runs.append(run_obj)
            normalized_segments.append(run_obj.expanded_run)
            cjk_buffer.clear()

        for char in text:
            if self._is_cjk_char(char):
                cjk_buffer.append(char)
            else:
                flush_cjk_buffer()
                normalized_segments.append(char)

        flush_cjk_buffer()

        full_normalized = "".join(normalized_segments)
        has_mark = self.ITERATION_MARK in text

        # Aggregate all bigrams across runs
        raw_tokens_set: set[str] = set()
        norm_tokens_set: set[str] = set()
        anchor_tokens_set: set[str] = set()

        for r in runs:
            raw_tokens_set.update(r.raw_bigrams)
            norm_tokens_set.update(r.normalized_bigrams)
            anchor_tokens_set.update(r.anchor_bigrams)

        # Include latin/ascii words if present
        for match in self._LATIN_WORD_RE.finditer(text):
            word = match.group(0).lower()
            if len(word) >= 2:
                raw_tokens_set.add(word)
                norm_tokens_set.add(word)

        tokens_dto = DisambiguatedCjkTokens(
            raw_tokens=tuple(sorted(raw_tokens_set)),
            normalized_tokens=tuple(sorted(norm_tokens_set)),
            anchor_tokens=tuple(sorted(anchor_tokens_set)),
        )

        return IterationExpansionResult(
            original_text=text,
            normalized_text=full_normalized,
            has_iteration_mark=has_mark,
            marks_expanded_count=marks_expanded_total,
            runs=tuple(runs),
            tokens=tokens_dto,
        )

    def _expand_single_cjk_run(self, raw_run: str) -> tuple[IterationMarkRun, int]:
        """Expand iteration marks inside a single contiguous CJK string run."""
        expanded_chars: list[str] = []
        expanded_indices: list[int] = []
        repeatable_han: str | None = None
        expanded_count = 0

        for idx, char in enumerate(raw_run):
            if char == self.ITERATION_MARK:
                if repeatable_han is not None:
                    expanded_chars.append(repeatable_han)
                    expanded_indices.append(idx)
                    expanded_count += 1
                else:
                    # Mark at start of run or following non-Han CJK: retain raw mark
                    expanded_chars.append(char)
            elif self._is_han_char(char):
                repeatable_han = char
                expanded_chars.append(char)
            else:
                # Kana, Hangul, or other CJK: cannot serve as antecedent for iteration mark
                repeatable_han = None
                expanded_chars.append(char)

        expanded_str = "".join(expanded_chars)

        # Build bigrams
        raw_bigrams = self._extract_bigrams(raw_run)
        norm_bigrams = self._extract_bigrams(expanded_str)

        # Anchors: bigrams covering the expanded indices
        anchor_set: set[str] = set()
        expanded_set = set(expanded_indices)
        for exp_idx in expanded_set:
            # Look at preceding and following bigram
            for offset in (exp_idx - 1, exp_idx):
                if 0 <= offset < len(expanded_chars) - 1:
                    anchor_set.add("".join(expanded_chars[offset : offset + 2]))

        return (
            IterationMarkRun(
                raw_run=raw_run,
                expanded_run=expanded_str,
                expanded_indices=tuple(expanded_indices),
                raw_bigrams=tuple(sorted(raw_bigrams)),
                normalized_bigrams=tuple(sorted(norm_bigrams)),
                anchor_bigrams=tuple(sorted(anchor_set)),
            ),
            expanded_count,
        )

    def _extract_bigrams(self, s: str) -> set[str]:
        """Generate overlapping two-character n-grams from a string."""
        if len(s) < 2:
            return {s} if len(s) == 1 else set()
        return {s[i : i + 2] for i in range(len(s) - 1)}

    def _is_han_char(self, char: str) -> bool:
        """Check if character is a canonical CJK Unified Ideograph."""
        return "\u4e00" <= char <= "\u9fff"

    def _is_cjk_char(self, char: str) -> bool:
        """Check if character belongs to common CJK ranges including marks and kana."""
        return (
            "\u4e00" <= char <= "\u9fff"  # CJK Unified Ideographs (Han)
            or "\u3040" <= char <= "\u309f"  # Hiragana
            or "\u30a0" <= char <= "\u30ff"  # Katakana
            or "\uac00" <= char <= "\ud7af"  # Hangul Syllables
            or char == self.ITERATION_MARK  # Ideographic Iteration Mark (々)
        )
