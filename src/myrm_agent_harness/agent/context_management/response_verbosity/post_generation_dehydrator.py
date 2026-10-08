"""Post-generation text dehydrator extracting concise TL;DR executive digests from verbose output.

[INPUT]
- DehydratedSummary: Contract models for dehydrated summaries.

[OUTPUT]
- PostGenerationDehydrator: Zero-cost heuristic summarizer extracting 3-point digests and action items.

[POS]
Post-processing layer in response verbosity subsystem fulfilling 1-click TL;DR user demands.
"""

from __future__ import annotations

import re

from .verbosity_types import DehydratedSummary


class PostGenerationDehydrator:
    """Extracts ultra-concise executive digests and key actionable takeaways from long model responses."""

    # Patterns matching headers, bullets, or concluding declarations
    KEY_POINT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*[-*•]\s+(.+)$", re.MULTILINE),
        re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE),
        re.compile(r"(?:conclusion|summary|takeaway|in short|tl;?dr|核心结论|总结|要点)[:：]\s*(.+)", re.IGNORECASE),
    )

    CODE_BLOCK_PATTERN: re.Pattern[str] = re.compile(r"```(?:\w+)?\n([\s\S]*?)\n```")
    GREETING_PATTERN: re.Pattern[str] = re.compile(
        r"^(?:hello|hi|sure|certainly|glad to help|here is|你好|您好|当然可以|没问题)[^.\n]*[.\n]",
        re.IGNORECASE,
    )

    def dehydrate(self, text: str, max_takeaways: int = 3) -> DehydratedSummary:
        """Compress verbose response text into a high-density executive digest."""
        clean_text = text.strip()
        if not clean_text:
            return DehydratedSummary(
                original_length_chars=0,
                dehydrated_length_chars=0,
                tldr_text="",
                key_takeaways=(),
                compression_ratio=1.0,
            )

        # Strip initial conversational greeting fluff
        stripped_text = self.GREETING_PATTERN.sub("", clean_text).strip()

        # Extract structured takeaways
        takeaways: list[str] = []
        for pat in self.KEY_POINT_PATTERNS:
            for match in pat.finditer(stripped_text):
                item = match.group(1).strip()
                # Exclude trivial short words
                if len(item) > 10 and item not in takeaways:
                    takeaways.append(item)
                    if len(takeaways) >= max_takeaways:
                        break
            if len(takeaways) >= max_takeaways:
                break

        # Fallback to leading sentences if no explicit bullet points exist
        if not takeaways:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", stripped_text) if len(s.strip()) > 15]
            takeaways = sentences[:max_takeaways]

        # Assemble compact TL;DR body
        bullets = tuple(takeaways)
        tldr_lines: list[str] = [f"- {t}" for t in bullets]
        tldr_body = "\n".join(tldr_lines) if tldr_lines else stripped_text[:200]

        orig_len = len(clean_text)
        dehydrated_len = len(tldr_body)
        ratio = round(dehydrated_len / orig_len, 3) if orig_len > 0 else 1.0

        return DehydratedSummary(
            original_length_chars=orig_len,
            dehydrated_length_chars=dehydrated_len,
            tldr_text=tldr_body,
            key_takeaways=bullets,
            compression_ratio=ratio,
        )
