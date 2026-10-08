"""Core engine for High-Density Clean Markdown Extraction and Context Sparsity Pruning.

Transforms bloated, noisy HTML (containing massive SVG vector dumps, scripts, ads) into dense,
clean Markdown under <100ms, and applies spatiotemporal sparsity pruning on long documents.

[INPUT]
- agent.context_management.clean_markdown_extractor.clean_markdown_types::CleanMarkdownExtractorConfig,
  ExtractedCleanContent, SparsityPruneResult (POS: Type contracts and models for Clean Markdown Extractor and
  Context Sparsity Pruning Suite.)

[OUTPUT]
- CleanMarkdownExtractorEngine: High-performance DOM purification and context sparsity pruning engine.

[POS]
Core engine for High-Density Clean Markdown Extraction and Context Sparsity Pruning.
"""

from __future__ import annotations

import re
import time
from myrm_agent_harness.agent.context_management.clean_markdown_extractor.clean_markdown_types import (
    CleanMarkdownExtractorConfig,
    ExtractedCleanContent,
    SparsityPruneResult,
)


class CleanMarkdownExtractorEngine:
    """High-performance DOM purification and context sparsity pruning engine."""

    def __init__(self, config: CleanMarkdownExtractorConfig | None = None) -> None:
        self.config: CleanMarkdownExtractorConfig = config or CleanMarkdownExtractorConfig()

    def extract_clean_markdown(
        self,
        raw_html: str,
        source_id: str = "",
    ) -> ExtractedCleanContent:
        """Purify raw HTML into high-density Markdown by removing SVG, scripts, styles, and chrome."""
        start_time = time.perf_counter()
        raw_char_count = len(raw_html)

        # 1. Extract Page Title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        if not title:
            h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", raw_html, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip() if h1_match else "Document"

        cleaned = raw_html

        # 2. Strip scripts, styles, and noscript
        if self.config.strip_scripts_styles:
            cleaned = re.sub(r"<script[\s\S]*?</script>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<style[\s\S]*?</style>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<noscript[\s\S]*?</noscript>", "", cleaned, flags=re.IGNORECASE)

        # 3. Strip SVG vector graphic code dumps (the primary cause of token bloating)
        if self.config.strip_svg:
            cleaned = re.sub(r"<svg[\s\S]*?</svg>", "", cleaned, flags=re.IGNORECASE)

        # 4. Strip navigation, headers, footers, and sidebars
        if self.config.strip_nav_footer:
            cleaned = re.sub(r"<nav[\s\S]*?</nav>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<footer[\s\S]*?</footer>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<aside[\s\S]*?</aside>", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<header[\s\S]*?</header>", "", cleaned, flags=re.IGNORECASE)

        # 5. Strip ad and promotional containers
        cleaned = re.sub(
            r"<div[^>]*class=[\"'][^\"']*(?:ad-|banner|promo|sponsor)[^\"']*[\"'][\s\S]*?</div>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        # 6. Strip inline Base64 data URIs
        if self.config.strip_inline_images:
            cleaned = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[inline-image]", cleaned)

        # 7. Convert semantic HTML elements to Markdown
        # Preformatted code blocks
        def _replace_pre(match: re.Match[str]) -> str:
            inner = re.sub(r"<[^>]+>", "", match.group(1))
            return f"\n\n```\n{inner.strip()}\n```\n\n"

        cleaned = re.sub(r"<pre[^>]*>(?:<code[^>]*>)?([\s\S]*?)(?:</code>)?</pre>", _replace_pre, cleaned, flags=re.IGNORECASE)

        # Headers
        cleaned = re.sub(r"<h1[^>]*>([\s\S]*?)</h1>", r"\n\n# \1\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<h2[^>]*>([\s\S]*?)</h2>", r"\n\n## \1\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<h3[^>]*>([\s\S]*?)</h3>", r"\n\n### \1\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<h[4-6][^>]*>([\s\S]*?)</h[4-6]>", r"\n\n#### \1\n\n", cleaned, flags=re.IGNORECASE)

        # Paragraphs and line breaks
        cleaned = re.sub(r"<p[^>]*>([\s\S]*?)</p>", r"\n\n\1\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)

        # Lists
        cleaned = re.sub(r"<li[^>]*>([\s\S]*?)</li>", r"\n- \1", cleaned, flags=re.IGNORECASE)

        # Clean remaining HTML tags
        cleaned = re.sub(r"<[^>]+>", "", cleaned)

        # Normalize whitespace and excessive blank lines
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        clean_char_count = len(cleaned)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        compression_ratio = round(clean_char_count / max(1, raw_char_count), 4)
        tokens_saved = max(
            0,
            int(raw_char_count / self.config.bytes_per_token_estimate)
            - int(clean_char_count / self.config.bytes_per_token_estimate),
        )

        return ExtractedCleanContent(
            source_url_or_id=source_id,
            title=title,
            clean_markdown=cleaned,
            raw_char_count=raw_char_count,
            clean_char_count=clean_char_count,
            compression_ratio=compression_ratio,
            tokens_saved=tokens_saved,
            duration_ms=round(duration_ms, 2),
            extracted_at=time.time(),
        )

    def apply_context_sparsity_pruning(
        self,
        markdown_text: str,
        query_focus: str | None = None,
        token_budget: int | None = None,
    ) -> SparsityPruneResult:
        """Apply spatiotemporal sparsity pruning by keeping focused sections and folding static background."""
        budget = token_budget or self.config.max_sparsity_budget_tokens
        original_tokens = max(1, int(len(markdown_text) / self.config.bytes_per_token_estimate))

        if original_tokens <= budget:
            return SparsityPruneResult(
                original_tokens=original_tokens,
                pruned_tokens=original_tokens,
                active_sections_kept=1,
                folded_sections_count=0,
                sparse_markdown=markdown_text,
                tokens_saved=0,
                savings_ratio=0.0,
            )

        # Split document by markdown headings
        raw_sections = re.split(r"(?m)(?=^#{1,3}\s+)", markdown_text)
        sections = [s.strip() for s in raw_sections if s.strip()]

        if len(sections) <= 1:
            # Fallback truncation if no heading structure exists
            truncated = markdown_text[: int(budget * self.config.bytes_per_token_estimate)] + "\n\n[... truncated by budget ...]"
            pruned_tokens = int(len(truncated) / self.config.bytes_per_token_estimate)
            return SparsityPruneResult(
                original_tokens=original_tokens,
                pruned_tokens=pruned_tokens,
                active_sections_kept=1,
                folded_sections_count=0,
                sparse_markdown=truncated,
                tokens_saved=max(0, original_tokens - pruned_tokens),
                savings_ratio=round((original_tokens - pruned_tokens) / original_tokens, 4),
            )

        focus_term = query_focus.lower() if query_focus else ""
        assembled_parts: list[str] = []
        active_kept = 0
        folded_count = 0

        for sec in sections:
            first_line = sec.splitlines()[0] if sec else ""
            sec_lower = sec.lower()

            # Always preserve sections matching focus query, or first section (intro)
            is_relevant = (focus_term in sec_lower) if focus_term else (active_kept < 2)

            if is_relevant:
                assembled_parts.append(sec)
                active_kept += 1
            else:
                # Fold non-focal background into a compact one-line anchor
                summary_line = sec.splitlines()[1] if len(sec.splitlines()) > 1 else ""
                fold_anchor = f"{first_line} [Folded background section · {len(sec)} chars · Summary: {summary_line[:80]}...]"
                assembled_parts.append(fold_anchor)
                folded_count += 1

        sparse_text = "\n\n".join(assembled_parts)
        pruned_tokens = max(1, int(len(sparse_text) / self.config.bytes_per_token_estimate))
        tokens_saved = max(0, original_tokens - pruned_tokens)

        return SparsityPruneResult(
            original_tokens=original_tokens,
            pruned_tokens=pruned_tokens,
            active_sections_kept=active_kept,
            folded_sections_count=folded_count,
            sparse_markdown=sparse_text,
            tokens_saved=tokens_saved,
            savings_ratio=round(tokens_saved / original_tokens, 4),
        )
