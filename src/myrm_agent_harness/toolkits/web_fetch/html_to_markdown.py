"""HTML to Markdown converter built on BeautifulSoup.

Provides API-compatible replacement for the vendored html2text (GPLv3) module.
Only depends on beautifulsoup4 (MIT) which is already a project dependency.

The converter supports headings, paragraphs, links, images, emphasis,
code blocks, lists, tables, blockquotes, and horizontal rules.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import ClassVar

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


@dataclass
class ConvertOptions:
    """Conversion parameters matching the html2text API surface used by callers."""

    body_width: int = 0
    ignore_emphasis: bool = False
    ignore_links: bool = False
    ignore_images: bool = False
    protect_links: bool = False
    single_line_break: bool = False
    mark_code: bool = False
    escape_snob: bool = False
    skip_internal_links: bool = True
    ignore_mailto_links: bool = True
    escape_backslash: bool = False
    escape_dot: bool = False
    escape_plus: bool = False
    escape_dash: bool = False
    include_sup_sub: bool = False
    preserve_tags: set[str] = field(default_factory=set)
    handle_code_in_pre: bool = False


_BLOCK_TAGS: set[str] = {
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "dialog",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}

_INLINE_TAGS: set[str] = {
    "a",
    "abbr",
    "b",
    "bdi",
    "bdo",
    "br",
    "cite",
    "code",
    "data",
    "dfn",
    "em",
    "i",
    "kbd",
    "mark",
    "q",
    "rp",
    "rt",
    "ruby",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
    "var",
    "wbr",
    "del",
    "ins",
    "strike",
}

_HEADING_TAGS: set[str] = {"h1", "h2", "h3", "h4", "h5", "h6"}

_MD_SPECIAL_RE: ClassVar[re.Pattern[str]] = re.compile(r"([\\`*_\[\]()#+\-!|>~{}])")

_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_TRAILING_SPACES_RE = re.compile(r" +\n")


def _escape_md(text: str) -> str:
    return _MD_SPECIAL_RE.sub(r"\\\1", text)


def _resolve_url(base: str, url: str) -> str:
    if not url or url.startswith(("http://", "https://", "mailto:", "data:", "//")):
        return url
    if not base:
        return url
    return urllib.parse.urljoin(base, url)


class HTML2Markdown:
    """Convert HTML to Markdown using BeautifulSoup.

    Designed as a drop-in replacement for the vendored html2text module,
    exposing the same ``handle()`` / ``update_params()`` API used by callers.
    """

    def __init__(self, baseurl: str = "", **kwargs: object) -> None:
        self._baseurl = baseurl
        self._opts = ConvertOptions()
        if kwargs:
            self.update_params(**kwargs)

    def update_params(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if key == "preserve_tags":
                self._opts.preserve_tags = set(value)  # type: ignore[arg-type]
            elif hasattr(self._opts, key):
                setattr(self._opts, key, value)

    def handle(self, html_str: str) -> str:
        if not html_str:
            return ""

        soup = BeautifulSoup(html_str, "html.parser")

        for tag in soup.find_all(["script", "style", "head"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        body = soup.find("body")
        root = body if body else soup

        result = self._convert_node(root)
        result = _TRAILING_SPACES_RE.sub("\n", result)
        result = _MULTI_NEWLINE_RE.sub("\n\n", result)
        return result.strip() + "\n" if result.strip() else ""

    def _convert_node(self, node: Tag | NavigableString) -> str:
        if isinstance(node, NavigableString):
            if isinstance(node, Comment):
                return ""
            text = str(node)
            text = html.unescape(text)
            text = re.sub(r"[ \t]+", " ", text)
            return text

        tag_name = node.name
        if tag_name is None:
            return self._convert_children(node)

        if tag_name in self._opts.preserve_tags:
            return str(node)

        handler = _TAG_HANDLERS.get(tag_name)
        if handler:
            return handler(self, node)

        if tag_name in _BLOCK_TAGS:
            inner = self._convert_children(node)
            return f"\n\n{inner.strip()}\n\n" if inner.strip() else ""

        return self._convert_children(node)

    def _convert_children(self, node: Tag) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, (NavigableString, Tag)):
                parts.append(self._convert_node(child))
        return "".join(parts)

    # ── Tag handlers ──────────────────────────────────────────

    def _handle_heading(self, tag: Tag) -> str:
        level = int(tag.name[1])
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        prefix = "#" * level
        return f"\n\n{prefix} {inner}\n\n"

    def _handle_p(self, tag: Tag) -> str:
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        if self._opts.single_line_break:
            return f"\n{inner}\n"
        return f"\n\n{inner}\n\n"

    def _handle_br(self, _tag: Tag) -> str:
        return "  \n"

    def _handle_hr(self, _tag: Tag) -> str:
        return "\n\n* * *\n\n"

    def _handle_blockquote(self, tag: Tag) -> str:
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        lines = inner.split("\n")
        quoted = "\n".join(f"> {line}" for line in lines)
        return f"\n\n{quoted}\n\n"

    def _handle_pre(self, tag: Tag) -> str:
        code_tag = tag.find("code", recursive=False)
        if code_tag and isinstance(code_tag, Tag):
            lang = ""
            classes = code_tag.get("class", [])
            if isinstance(classes, list):
                for cls in classes:
                    if isinstance(cls, str) and cls.startswith("language-"):
                        lang = cls[9:]
                        break
                    elif isinstance(cls, str) and cls.startswith("lang-"):
                        lang = cls[5:]
                        break
            text = code_tag.get_text()
        else:
            text = tag.get_text()
            lang = ""

        if text and not text.endswith("\n"):
            text += "\n"
        return f"\n\n```{lang}\n{text}```\n\n"

    def _handle_code(self, tag: Tag) -> str:
        parent = tag.parent
        if parent and parent.name == "pre":
            return tag.get_text()
        text = tag.get_text()
        if not text:
            return ""
        if "`" in text:
            max_run = max((len(m) for m in re.findall(r"`+", text)), default=0)
            fence = "`" * (max_run + 1)
            needs_pad = text.startswith("`") or text.endswith("`")
            body = f" {text} " if needs_pad else text
            return f"{fence}{body}{fence}"
        return f"`{text}`"

    def _handle_emphasis(self, tag: Tag) -> str:
        if self._opts.ignore_emphasis:
            return self._convert_children(tag)
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        return f"_{inner}_"

    def _handle_strong(self, tag: Tag) -> str:
        if self._opts.ignore_emphasis:
            return self._convert_children(tag)
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        return f"**{inner}**"

    def _handle_strikethrough(self, tag: Tag) -> str:
        if self._opts.ignore_emphasis:
            return self._convert_children(tag)
        inner = self._convert_children(tag).strip()
        if not inner:
            return ""
        return f"~~{inner}~~"

    def _handle_link(self, tag: Tag) -> str:
        href = tag.get("href", "") or ""
        if isinstance(href, list):
            href = href[0] if href else ""

        if self._opts.ignore_links:
            return self._convert_children(tag)

        if self._opts.ignore_mailto_links and str(href).startswith("mailto:"):
            return self._convert_children(tag)

        if self._opts.skip_internal_links and str(href).startswith("#"):
            return self._convert_children(tag)

        href = _resolve_url(self._baseurl, str(href))
        inner = self._convert_children(tag).strip()
        if not inner:
            inner = href

        title = tag.get("title", "")
        if title:
            return f'[{inner}]({href} "{title}")'
        return f"[{inner}]({href})"

    def _handle_img(self, tag: Tag) -> str:
        if self._opts.ignore_images:
            return ""
        src = tag.get("src", "") or ""
        if isinstance(src, list):
            src = src[0] if src else ""
        src = _resolve_url(self._baseurl, str(src))
        alt = tag.get("alt", "") or ""
        if isinstance(alt, list):
            alt = " ".join(alt)
        title = tag.get("title", "")
        if title:
            return f'![{alt}]({src} "{title}")'
        return f"![{alt}]({src})"

    def _handle_ul(self, tag: Tag) -> str:
        items: list[str] = []
        for child in tag.children:
            if isinstance(child, Tag) and child.name == "li":
                inner = self._convert_children(child).strip()
                if inner:
                    indent_inner = inner.replace("\n", "\n  ")
                    items.append(f"* {indent_inner}")
        if not items:
            return ""
        return "\n\n" + "\n".join(items) + "\n\n"

    def _handle_ol(self, tag: Tag) -> str:
        items: list[str] = []
        start = int(tag.get("start", 1) or 1)
        idx = start
        for child in tag.children:
            if isinstance(child, Tag) and child.name == "li":
                inner = self._convert_children(child).strip()
                if inner:
                    pad = " " * (len(str(idx)) + 2)
                    indent_inner = inner.replace("\n", f"\n{pad}")
                    items.append(f"{idx}. {indent_inner}")
                    idx += 1
        if not items:
            return ""
        return "\n\n" + "\n".join(items) + "\n\n"

    def _handle_table(self, tag: Tag) -> str:
        rows: list[list[str]] = []
        for tr in tag.find_all("tr"):
            if not isinstance(tr, Tag):
                continue
            cells: list[str] = []
            for cell in tr.children:
                if isinstance(cell, Tag) and cell.name in ("td", "th"):
                    text = self._convert_children(cell).strip()
                    text = text.replace("|", "\\|").replace("\n", " ")
                    cells.append(text)
            if cells:
                rows.append(cells)

        if not rows:
            return self._convert_children(tag)

        max_cols = max(len(r) for r in rows)
        for row in rows:
            while len(row) < max_cols:
                row.append("")

        has_header = tag.find("thead") is not None
        lines: list[str] = []

        if has_header and rows:
            header = rows[0]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")
        else:
            if rows:
                lines.append("| " + " | ".join("" for _ in rows[0]) + " |")
                lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
            for row in rows:
                lines.append("| " + " | ".join(row) + " |")

        return "\n\n" + "\n".join(lines) + "\n\n"

    def _handle_li(self, tag: Tag) -> str:
        return self._convert_children(tag)

    def _handle_sup(self, tag: Tag) -> str:
        if self._opts.include_sup_sub:
            inner = self._convert_children(tag).strip()
            return f"<sup>{inner}</sup>" if inner else ""
        return self._convert_children(tag)

    def _handle_sub(self, tag: Tag) -> str:
        if self._opts.include_sup_sub:
            inner = self._convert_children(tag).strip()
            return f"<sub>{inner}</sub>" if inner else ""
        return self._convert_children(tag)

    def _handle_q(self, tag: Tag) -> str:
        inner = self._convert_children(tag).strip()
        return f'"{inner}"' if inner else ""

    def _handle_abbr(self, tag: Tag) -> str:
        return self._convert_children(tag)

    def _handle_div(self, tag: Tag) -> str:
        inner = self._convert_children(tag)
        stripped = inner.strip()
        if not stripped:
            return ""
        if self._opts.single_line_break:
            return f"\n{stripped}\n"
        return f"\n\n{stripped}\n\n"


_TAG_HANDLERS: dict[str, object] = {
    "h1": HTML2Markdown._handle_heading,
    "h2": HTML2Markdown._handle_heading,
    "h3": HTML2Markdown._handle_heading,
    "h4": HTML2Markdown._handle_heading,
    "h5": HTML2Markdown._handle_heading,
    "h6": HTML2Markdown._handle_heading,
    "p": HTML2Markdown._handle_p,
    "br": HTML2Markdown._handle_br,
    "hr": HTML2Markdown._handle_hr,
    "blockquote": HTML2Markdown._handle_blockquote,
    "pre": HTML2Markdown._handle_pre,
    "code": HTML2Markdown._handle_code,
    "em": HTML2Markdown._handle_emphasis,
    "i": HTML2Markdown._handle_emphasis,
    "u": HTML2Markdown._handle_emphasis,
    "strong": HTML2Markdown._handle_strong,
    "b": HTML2Markdown._handle_strong,
    "s": HTML2Markdown._handle_strikethrough,
    "del": HTML2Markdown._handle_strikethrough,
    "strike": HTML2Markdown._handle_strikethrough,
    "a": HTML2Markdown._handle_link,
    "img": HTML2Markdown._handle_img,
    "ul": HTML2Markdown._handle_ul,
    "ol": HTML2Markdown._handle_ol,
    "li": HTML2Markdown._handle_li,
    "table": HTML2Markdown._handle_table,
    "div": HTML2Markdown._handle_div,
    "sup": HTML2Markdown._handle_sup,
    "sub": HTML2Markdown._handle_sub,
    "q": HTML2Markdown._handle_q,
    "abbr": HTML2Markdown._handle_abbr,
}


class CustomHTML2Text(HTML2Markdown):
    """API-compatible wrapper preserving the exact interface used by callers.

    Matches the ``CustomHTML2Text(baseurl=...)`` / ``update_params(...)`` /
    ``handle(html)`` call pattern from pipeline.py and markdown_generator.py.
    """

    pass
