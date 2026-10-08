# [INPUT] DeepExtractResult
# [OUTPUT] SelectiveDeepExtractCleaner
# [POS] Stage 2 selective deep web content cleanser, noise stripper, and markdown normalizer

"""Selective deep extract content cleaner stripping navigation, ads, and boilerplate noise."""

from __future__ import annotations

import re

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    DeepExtractResult,
)


class SelectiveDeepExtractCleaner:
    """Cleanses raw web HTML/text into dense, high-signal markdown for Stage 2 consumption."""

    def __init__(self) -> None:
        self._boilerplate_patterns: list[re.Pattern[str]] = [
            re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE),
            re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE),
            re.compile(r"<nav[\s\S]*?</nav>", re.IGNORECASE),
            re.compile(r"<footer[\s\S]*?</footer>", re.IGNORECASE),
            re.compile(r"<header[\s\S]*?</header>", re.IGNORECASE),
            re.compile(r"<!--[\s\S]*?-->"),
            re.compile(r"(?i)\b(all rights reserved|cookie policy|privacy policy|terms of service)\b.*$"),
        ]
        self._html_tag_re = re.compile(r"<[^>]+>")
        self._excessive_newlines_re = re.compile(r"\n{3,}")

    def clean_raw_html_or_text(
        self,
        url: str,
        title: str,
        raw_content: str,
        fetch_turn: int = 1,
    ) -> DeepExtractResult:
        """Strip boilerplate noise and return a sanitized markdown representation."""
        original_len = len(raw_content)
        if not raw_content:
            return DeepExtractResult(
                url=url,
                title=title or "Empty Document",
                cleaned_markdown="",
                original_char_len=0,
                cleaned_char_len=0,
                compression_ratio=1.0,
                fetch_turn=fetch_turn,
            )

        text = raw_content

        # 1. Strip script, style, nav, footer, headers
        for pattern in self._boilerplate_patterns:
            text = pattern.sub("", text)

        # 2. Strip remaining HTML tags
        text = self._html_tag_re.sub(" ", text)

        # 3. Normalize whitespace line by line
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            # Drop obvious noise or single-character lines
            if not stripped:
                continue
            if len(stripped) <= 2 and not stripped.isalnum():
                continue
            lines.append(stripped)

        cleaned_body = "\n\n".join(lines)
        cleaned_body = self._excessive_newlines_re.sub("\n\n", cleaned_body).strip()

        # 4. Construct normalized markdown header
        display_title = title.strip() or "Web Document"
        formatted_markdown = f"# {display_title}\n\n**Source**: {url}\n\n{cleaned_body}"
        cleaned_len = len(formatted_markdown)

        compression_ratio = (
            round(cleaned_len / original_len, 4) if original_len > 0 else 1.0
        )

        return DeepExtractResult(
            url=url,
            title=display_title,
            cleaned_markdown=formatted_markdown,
            original_char_len=original_len,
            cleaned_char_len=cleaned_len,
            compression_ratio=compression_ratio,
            fetch_turn=fetch_turn,
            cached=False,
        )
