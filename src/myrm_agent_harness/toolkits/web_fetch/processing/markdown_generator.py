"""Markdown generator

will HTML convertsas Markdown, supportscode blockformatandchainrefuseconverts.

[INPUT]
- (none)

[OUTPUT]
- MarkdownResult: Markdown generatesresult
- ContentFilter: contentfilterprotocol
- MarkdownGenerator: HTML → Markdown generator, supportscode blockandcontentfi...

[POS]
Markdown generator
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_LINK_PATTERN = re.compile(r'!?\[([^\]]+)\]\(([^)]+?)(?:\s+"([^"]*)")?\)')


@dataclass(slots=True)
class MarkdownResult:
    """Markdown generatesresult"""

    raw_markdown: str = ""
    markdown_with_citations: str = ""
    references_markdown: str = ""
    fit_markdown: str = ""
    fit_html: str = ""
    was_truncated: bool = False


@runtime_checkable
class ContentFilter(Protocol):
    """contentfilterprotocol"""

    def filter_content(self, html: str, max_chars: int = 0) -> tuple[list[str], bool]: ...


def _fast_urljoin(base: str, url: str) -> str:
    if url.startswith(("http://", "https://", "mailto:", "//")):
        return url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return urljoin(base, url)


def _convert_links_to_citations(markdown: str, base_url: str = "") -> tuple[str, str]:
    """will Markdown inchainconvertsasrefuseformat"""
    link_map: dict[str, tuple[int, str]] = {}
    url_cache: dict[str, str] = {}
    parts: list[str] = []
    last_end = 0
    counter = 1

    for match in _LINK_PATTERN.finditer(markdown):
        parts.append(markdown[last_end : match.start()])
        text, url, title = match.groups()

        if base_url and not url.startswith(("http://", "https://", "mailto:")):
            if url not in url_cache:
                url_cache[url] = _fast_urljoin(base_url, url)
            url = url_cache[url]

        if url not in link_map:
            desc_parts: list[str] = []
            if title:
                desc_parts.append(title)
            if text and text != title:
                desc_parts.append(text)
            link_map[url] = (counter, ": " + " - ".join(desc_parts) if desc_parts else "")
            counter += 1

        num = link_map[url][0]
        if match.group(0).startswith("!"):
            parts.append(f"![{text}⟨{num}⟩]")
        else:
            parts.append(f"{text}⟨{num}⟩")
        last_end = match.end()

    parts.append(markdown[last_end:])
    converted_text = "".join(parts)

    references = ["\n\n## References\n\n"]
    references.extend(f"⟨{num}⟩ {url}{desc}\n" for url, (num, desc) in sorted(link_map.items(), key=lambda x: x[1][0]))
    return converted_text, "".join(references)


class MarkdownGenerator:
    """HTML → Markdown generator, supportscode blockandcontentfilter"""

    def __init__(
        self,
        content_filter: ContentFilter | None = None,
        options: dict[str, object] | None = None,
    ):
        self.content_filter = content_filter
        self.options = options or {}

    def generate_markdown(
        self,
        input_html: str,
        base_url: str = "",
        html2text_options: dict[str, object] | None = None,
        content_filter: ContentFilter | None = None,
        citations: bool = True,
        max_chars: int = 0,
    ) -> MarkdownResult:
        from .html_to_markdown import CustomHTML2Text

        try:
            h = CustomHTML2Text(baseurl=base_url)
            default_options: dict[str, object] = {
                "body_width": 0,
                "ignore_emphasis": False,
                "ignore_links": False,
                "ignore_images": False,
                "protect_links": False,
                "single_line_break": False,
                "mark_code": False,
                "escape_snob": False,
                "skip_internal_links": True,
            }

            if html2text_options:
                default_options.update(html2text_options)
            elif self.options:
                default_options.update(self.options)

            h.update_params(**default_options)

            if not input_html:
                input_html = ""

            try:
                raw_markdown = h.handle(input_html)
            except Exception as e:
                raw_markdown = f"Error converting HTML to markdown: {e}"

            raw_markdown = raw_markdown.replace("    ```", "```")

            markdown_with_citations: str = raw_markdown
            references_markdown: str = ""
            if citations:
                try:
                    markdown_with_citations, references_markdown = _convert_links_to_citations(raw_markdown, base_url)
                except Exception as e:
                    markdown_with_citations = raw_markdown
                    references_markdown = f"Error generating citations: {e}"

            fit_markdown: str = ""
            filtered_html: str = ""
            active_filter = content_filter or self.content_filter
            was_truncated = False
            if active_filter:
                try:
                    filtered_segments, was_truncated = active_filter.filter_content(input_html, max_chars)
                    filtered_html = "\n".join(f"<div>{s}</div>" for s in filtered_segments)
                    fit_markdown = h.handle(filtered_html)
                except Exception as e:
                    fit_markdown = f"Error generating fit markdown: {e}"
                    filtered_html = ""

            return MarkdownResult(
                raw_markdown=raw_markdown or "",
                markdown_with_citations=markdown_with_citations or "",
                references_markdown=references_markdown or "",
                fit_markdown=fit_markdown or "",
                fit_html=filtered_html or "",
                was_truncated=was_truncated,
            )
        except Exception as e:
            error_msg = f"Error in markdown generation: {e}"
            return MarkdownResult(
                raw_markdown=error_msg,
                markdown_with_citations=error_msg,
            )
