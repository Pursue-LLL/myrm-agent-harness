"""Four-Tier Progressive Context Compression Pipeline.

Implements Tokenomics-inspired multi-stage compression:
- Tier 1: Lossless clean (whitespace normalization, Headroom tabular JSON, URL trims)
- Tier 2: Structural dedup (Session-Dedup content hashing, CCR markers)
- Tier 3: Semantic pruning (Caveman prose stripping, shielded by protected patterns)
- Tier 4: Extreme compaction (Ultra aggressive atomic pruning)

[INPUT]
- runtime.context.protected_patterns_matcher::ProtectedPatternsMatcher (POS: Protected patterns matcher and
  syntax safety shield.)
- runtime.context.tokenomics_compression_types::CompressionTierKind, TieredCompressionResult (POS: Strongly
  typed data contracts for the Four-Tier Tokenomics context compression engine.)

[OUTPUT]
- TieredContextCompressionPipeline: Orchestrates progressive context compression across the four Tokenomics
  tiers.

[POS]
Four-Tier Progressive Context Compression Pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.protected_patterns_matcher import (
    ProtectedPatternsMatcher,
)
from myrm_agent_harness.runtime.context.tokenomics_compression_types import (
    CompressionTierKind,
    TieredCompressionResult,
)


class TieredContextCompressionPipeline:
    """Orchestrates progressive context compression across the four Tokenomics tiers."""

    POLITE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(
            r"\b(?:certainly|sure thing|absolutely|i would be happy to help with that|as requested)[,!.]?\s*",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:let me know if you need anything else|feel free to ask|hope this helps|thank you for your patience)[.!]?\s*",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:i understand your request|i will proceed to|as an ai language model)[,!.]?\s*",
            re.IGNORECASE,
        ),
    )

    URL_TRACKING_REGEX: re.Pattern[str] = re.compile(
        r"(\?|&)(?:utm_[a-zA-Z_]+|fbclid|gclid|ref|source)=[^&\s)]+"
    )

    def __init__(
        self,
        matcher: ProtectedPatternsMatcher | None = None,
        min_dedup_length: int = 80,
    ) -> None:
        self.matcher = matcher or ProtectedPatternsMatcher()
        self.min_dedup_length = min_dedup_length
        self._content_hash_store: dict[str, int] = {}

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Lightweight token estimator (~4 chars per token)."""
        return max(1, len(text) // 4)

    def apply_tier_1_lossless(self, text: str) -> str:
        """Tier 1: Lossless whitespace normalization, URL parameter cleanup, and Headroom JSON."""
        # 1. Normalize excessive newlines
        processed = re.sub(r"\n{3,}", "\n\n", text)
        processed = re.sub(r"[ \t]+(?=\n)", "", processed).strip()

        # 2. Trim URL tracking noise
        processed = self.URL_TRACKING_REGEX.sub("", processed)

        # 3. Headroom: Extract common keys from repeated JSON objects in array blocks
        processed = self._compress_json_arrays(processed)
        return processed

    def _compress_json_arrays(self, text: str) -> str:
        """Find JSON arrays of homogenous dicts and format them in compact tabular form."""
        # Detect JSON arrays
        pattern = re.compile(r"\[\s*\{[\s\S]*?\}\s*\]")

        def replace_json_array(match: re.Match[str]) -> str:
            snippet = match.group(0)
            try:
                data = json.loads(snippet)
                if isinstance(data, list) and len(data) >= 2 and all(isinstance(x, dict) for x in data):
                    keys = list(data[0].keys())
                    if all(list(d.keys()) == keys for d in data):
                        # Convert to tabular compact representation
                        rows: list[list[str]] = [[str(d.get(k, "")) for k in keys] for d in data]
                        return json.dumps({"_headroom_columns": keys, "_rows": rows}, separators=(",", ":"))
            except Exception:
                pass
            return snippet

        return pattern.sub(replace_json_array, text)

    def apply_tier_2_structural_dedup(self, text: str, current_turn: int) -> str:
        """Tier 2: Content-hash addressing and CCR retrieval markers for duplicate blocks."""
        paragraphs = text.split("\n\n")
        rebuilt: list[str] = []

        for p in paragraphs:
            content = p.strip()
            if len(content) >= self.min_dedup_length:
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                prev_turn = self._content_hash_store.get(digest)
                if prev_turn is not None and prev_turn < current_turn:
                    # Replace with compact CCR retrieval marker
                    rebuilt.append(
                        f"[Duplicate content hash:{digest[:12]} presented in turn {prev_turn}]"
                    )
                    continue
                self._content_hash_store[digest] = current_turn

            rebuilt.append(p)

        return "\n\n".join(rebuilt)

    def apply_tier_3_semantic_pruning(self, text: str) -> str:
        """Tier 3: Caveman prose trimming shielded by protected patterns."""
        # 1. Mask protected entities (code blocks, paths, line numbers, error codes)
        masked, placeholders = self.matcher.mask_protected_entities(text)

        # 2. Strip polite conversational filler
        for pattern in self.POLITE_PATTERNS:
            masked = pattern.sub("", masked)

        # 3. Restore all protected entities verbatim
        return self.matcher.restore_protected_entities(masked, placeholders).strip()

    def apply_tier_4_extreme(self, text: str) -> str:
        """Tier 4: Ultra aggressive atomic pruning of descriptive narratives."""
        masked, placeholders = self.matcher.mask_protected_entities(text)

        lines = masked.splitlines()
        retained_lines: list[str] = []

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue
            # Keep bullet points, headers, or lines containing protected placeholders
            if (
                trimmed.startswith(("-", "*", "#", "1.", "2.", "3.", "4.", "5."))
                or self.matcher.PLACEHOLDER_PREFIX in trimmed
                or "error" in trimmed.lower()
            ):
                retained_lines.append(trimmed)

        compacted = "\n".join(retained_lines) if retained_lines else masked
        return self.matcher.restore_protected_entities(compacted, placeholders).strip()

    def execute_pipeline(
        self,
        text: str,
        active_tiers: Sequence[CompressionTierKind],
        current_turn: int = 1,
    ) -> TieredCompressionResult:
        """Run text sequentially through configured compression tiers."""
        original_tokens = self._estimate_tokens(text)
        current_text = text

        if CompressionTierKind.TIER_1_LOSSLESS_CLEAN in active_tiers:
            current_text = self.apply_tier_1_lossless(current_text)

        if CompressionTierKind.TIER_2_STRUCTURAL_DEDUP in active_tiers:
            current_text = self.apply_tier_2_structural_dedup(current_text, current_turn)

        if CompressionTierKind.TIER_3_SEMANTIC_PRUNING in active_tiers:
            current_text = self.apply_tier_3_semantic_pruning(current_text)

        if CompressionTierKind.TIER_4_EXTREME_COMPACTION in active_tiers:
            current_text = self.apply_tier_4_extreme(current_text)

        compressed_tokens = self._estimate_tokens(current_text)
        reduction_ratio = (
            round((original_tokens - compressed_tokens) / original_tokens, 4)
            if original_tokens > 0
            else 0.0
        )

        _, placeholders = self.matcher.mask_protected_entities(current_text)

        return TieredCompressionResult(
            original_tokens_est=original_tokens,
            compressed_tokens_est=compressed_tokens,
            reduction_ratio=max(0.0, reduction_ratio),
            tiers_applied=tuple(active_tiers),
            processed_text=current_text,
            protected_spans_preserved=len(placeholders),
        )
