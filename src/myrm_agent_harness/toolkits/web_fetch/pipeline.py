"""ContentPipeline — Converts HTML into LLM-friendly Documents.

Unified content processing pipeline, decoupled from the Fetcher layer:
regardless of whether HTML comes from curl_cffi, Patchright, or Scrapling,
it passes through the same processing pipeline.

[INPUT]
web_fetch.content_pruning::ContentPruningFilter (POS: Boilerplate / noise pruning)
web_fetch.fetchers.protocol::FetcherType, FetchResult (POS: Fetcher protocol types)
web_fetch.markdown_generator::MarkdownGenerator (POS: HTML-to-Markdown conversion)
utils.text_cleaner::clean_text (POS: Generic text cleaning utility)

[OUTPUT]
ContentPipeline: Transforms raw FetchResult HTML into cleaned, Markdown-formatted Documents

[POS]
Content processing pipeline. Sits between the fetcher layer and the consumer layer,
converting raw HTML into clean Markdown Documents with metadata.

"""

from __future__ import annotations

import logging
import re

from langchain_core.documents import Document

from myrm_agent_harness.utils.text_cleaner import clean_text

from .content_pruning import ContentPruningFilter
from .fetchers.protocols import FetcherType, FetchResult
from .markdown_generator import MarkdownGenerator

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

logger = logging.getLogger(__name__)

_MIN_CONTENT_LENGTH = 50
_FIT_MARKDOWN_THRESHOLD = 100


class ContentPipeline:
    """HTML → filter → Markdown → Document"""

    def __init__(self, *, use_raw_markdown: bool = False):
        self._use_raw_markdown = use_raw_markdown
        self._md_generator = self._create_markdown_generator()

    def _create_markdown_generator(self) -> MarkdownGenerator | None:
        if self._use_raw_markdown:
            return None
        return MarkdownGenerator(
            content_filter=ContentPruningFilter(
                threshold=0.48,
                metric_weights={
                    "text_density": 0.32,
                    "link_density": 0.25,
                    "tag_weight": 0.33,
                    "class_id_weight": 0.08,
                    "text_length": 0.02,
                },
            ),
        )

    def _extract_raw_markdown(self, html: str, base_url: str) -> str:
        from .html_to_markdown import CustomHTML2Text

        h = CustomHTML2Text(baseurl=base_url)
        h.update_params(body_width=0)
        return h.handle(html).strip()

    def _extract_with_generator(
        self, html: str, base_url: str, is_stealth: bool, max_chars: int = 0
    ) -> tuple[str, bool]:
        assert self._md_generator is not None
        result = self._md_generator.generate_markdown(
            input_html=html,
            base_url=base_url,
            content_filter=self._md_generator.content_filter,
            max_chars=max_chars,
        )

        fit = result.fit_markdown.strip()
        if is_stealth:
            if not fit or len(fit) < _FIT_MARKDOWN_THRESHOLD:
                logger.warning("fit_markdown too short for stealth page, falling back to raw_markdown")
                return clean_text(result.raw_markdown), result.was_truncated
            return clean_text(fit), result.was_truncated

        return (fit, result.was_truncated) if len(fit) > _FIT_MARKDOWN_THRESHOLD else ("", False)

    def process(self, fetch_result: FetchResult, max_chars: int = 0) -> Document | None:
        """will FetchResult 's HTML convertsas Document"""
        was_truncated = False
        if self._md_generator is None:
            content = self._extract_raw_markdown(fetch_result.html, fetch_result.url)
            if max_chars > 0 and len(content) > max_chars:
                content = content[:max_chars] + "\n\n[TRUNCATED]"
                was_truncated = True
        else:
            is_stealth = fetch_result.fetcher_type == FetcherType.STEALTH
            content, was_truncated = self._extract_with_generator(
                fetch_result.html, fetch_result.url, is_stealth, max_chars
            )

        if not content or len(content.strip()) < _MIN_CONTENT_LENGTH:
            return None

        title_match = _TITLE_RE.search(fetch_result.html)
        title = title_match.group(1).strip() if title_match else ""
        metadata: dict[str, str | bool] = {
            "url": fetch_result.url,
            "title": title,
            "description": "",
            "was_truncated": was_truncated,
        }

        return Document(page_content=content, metadata=metadata)
