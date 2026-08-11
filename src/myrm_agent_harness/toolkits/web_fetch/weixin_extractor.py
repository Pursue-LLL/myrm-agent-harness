"""WeChat Official Account article extractor (mp.weixin.qq.com fast path).

[POS]
Fetches public WeChat articles with a MicroMessenger User-Agent and extracts
``#js_content`` as Markdown. Uses a host-allowlisted urllib lane so L1 can succeed
when HttpFetcher SSRF DNS pinning maps the host to a local fake-IP proxy range.

When extraction fails or the page is blocked, FetchEngine falls back to the
standard L1/L2/L3 degradation pipeline (Browser handles verification pages).

[INPUT]
- mp.weixin.qq.com 文章 URL

[OUTPUT]
- is_weixin_article_url: Detect mp.weixin.qq.com article links
- get_weixin_request_headers: Optional L1 headers for mp.weixin.qq.com
- extract_weixin_article: Fetch + parse article as Document, or None
- parse_weixin_article_html: Parse HTML into Document (shared by L1 fast path and L2)
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_ALLOWED_HOST = "mp.weixin.qq.com"
_MICROMESSENGER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.38(0x18002633) NetType/WIFI Language/zh_CN"
)
_REFERER = "https://mp.weixin.qq.com/"
_BLOCK_MARKERS = ("环境异常", "完成验证后即可继续访问")
_REQUEST_TIMEOUT = 15
_MIN_BODY_CHARS = 80
_MAX_RESPONSE_BYTES = 750_000
_MAX_BODY_CHARS = 20_000
_MAX_IMAGES = 30
_CREATE_TIME_RE = re.compile(r"var\s+createTime\s*=\s*['\"]([^'\"]+)['\"]")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirect blocked: {newurl}", headers, fp
        )


def is_weixin_article_url(url: str) -> bool:
    """Return True when *url* is a WeChat Official Account article link."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host != _ALLOWED_HOST and not host.endswith(f".{_ALLOWED_HOST}"):
        return False
    path = parsed.path or ""
    return path == "/s" or path.startswith("/s/")


def get_weixin_request_headers(hostname: str) -> dict[str, str]:
    """Return extra HTTP headers for mp.weixin.qq.com L1 requests."""
    host = hostname.lower()
    if host == _ALLOWED_HOST or host.endswith(f".{_ALLOWED_HOST}"):
        return {"User-Agent": _MICROMESSENGER_UA, "Referer": _REFERER}
    return {}


def _is_blocked_page(html_text: str) -> bool:
    if "js_content" in html_text:
        return False
    return any(marker in html_text for marker in _BLOCK_MARKERS)


def _first_meta(
    soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None
) -> str:
    if property_name:
        tag = soup.find("meta", property=property_name)
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in (
        lambda: soup.find(id="activity-name"),
        lambda: soup.find("meta", property="og:title"),
        lambda: soup.find("title"),
    ):
        node = selector()
        if node is None:
            continue
        if node.name == "meta":
            content = node.get("content")
            text = str(content).strip() if content else ""
        else:
            text = node.get_text(" ", strip=True)
        if text:
            return html.unescape(text)
    return ""


def _extract_author(soup: BeautifulSoup) -> str:
    for selector in (
        lambda: soup.find(id="js_name"),
        lambda: soup.find(id="js_author_name"),
        lambda: soup.find("a", id="js_name"),
    ):
        node = selector()
        if node is not None:
            text = node.get_text(" ", strip=True)
            if text:
                return html.unescape(text)
    return _first_meta(soup, property_name="og:article:author")


def _extract_publish_time(soup: BeautifulSoup) -> str:
    for selector in (
        lambda: soup.find(id="publish_time"),
        lambda: soup.find("em", id="publish_time"),
    ):
        node = selector()
        if node is not None:
            text = node.get_text(" ", strip=True)
            if text:
                return html.unescape(text)
    og_time = _first_meta(soup, property_name="og:article:published_time")
    if og_time:
        return og_time
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        match = _CREATE_TIME_RE.search(script_text)
        if match:
            return match.group(1).strip()
    return ""


def _normalize_lazy_images(content_div: Tag) -> None:
    for img in content_div.find_all("img"):
        data_src = img.get("data-src")
        if isinstance(data_src, list):
            data_src = data_src[0] if data_src else ""
        if isinstance(data_src, str) and data_src.startswith("http"):
            img["src"] = data_src


def _collect_image_urls(content_div: Tag) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in content_div.find_all("img"):
        src = img.get("data-src") or img.get("src")
        if isinstance(src, list):
            src = src[0] if src else ""
        if not isinstance(src, str) or not src.startswith("http"):
            continue
        if src in seen:
            continue
        seen.add(src)
        urls.append(src)
        if len(urls) >= _MAX_IMAGES:
            break
    return urls


def _content_div_to_markdown(content_div: Tag) -> str:
    from .html_to_markdown import CustomHTML2Text

    _normalize_lazy_images(content_div)
    fragment = str(content_div)
    converter = CustomHTML2Text(baseurl=_REFERER.rstrip("/"))
    converter.update_params(body_width=0, ignore_images=False)
    markdown = converter.handle(fragment).strip()
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    if len(markdown) > _MAX_BODY_CHARS:
        markdown = (
            markdown[:_MAX_BODY_CHARS] + "\n\n…（正文超长已截断 / body truncated）"
        )
    return markdown


def has_weixin_js_content(html_text: str) -> bool:
    """Return True when HTML contains WeChat article body container."""
    return 'id="js_content"' in html_text or "id='js_content'" in html_text


def parse_weixin_article_html(html_text: str, *, url: str) -> Document | None:
    """Parse fetched WeChat article HTML into a Document."""
    if _is_blocked_page(html_text):
        return None

    if not has_weixin_js_content(html_text):
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    content_div = soup.find(id="js_content")
    if content_div is None or not isinstance(content_div, Tag):
        return None

    image_urls = _collect_image_urls(content_div)
    body = _content_div_to_markdown(content_div)
    if len(body.strip()) < _MIN_BODY_CHARS:
        return None

    title = _extract_title(soup)
    author = _extract_author(soup)
    publish_time = _extract_publish_time(soup)
    description = _first_meta(soup, name="description")

    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    if author:
        parts.append(f"**作者**: {author}")
    if publish_time:
        parts.append(f"**发布时间**: {publish_time}")
    if description and description != title:
        parts.append(description)
    parts.append(body)
    page_content = "\n\n".join(parts)

    metadata: dict[str, str] = {
        "url": url,
        "title": title,
        "description": description,
        "source_type": "weixin_article",
    }
    if author:
        metadata["author"] = author
    if publish_time:
        metadata["publish_time"] = publish_time
    if image_urls:
        metadata["image_urls"] = json.dumps(image_urls, ensure_ascii=False)

    return Document(page_content=page_content, metadata=metadata)


def _build_opener(proxy_pool: ProxyPool | None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [_NoRedirectHandler()]
    if proxy_pool:
        proxy_config = proxy_pool.get_next()
        proxy_url = proxy_config.to_url()
        handlers.append(
            urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        )
    handlers.append(urllib.request.HTTPHandler())
    handlers.append(urllib.request.HTTPSHandler())
    return urllib.request.build_opener(*handlers)


def _fetch_html(url: str, opener: urllib.request.OpenerDirector) -> str | None:
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "User-Agent": _MICROMESSENGER_UA,
            "Referer": _REFERER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with opener.open(req, timeout=_REQUEST_TIMEOUT) as resp:
        raw = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            logger.warning("Weixin article response exceeded size cap for %s", url)
            raw = raw[:_MAX_RESPONSE_BYTES]
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


async def extract_weixin_article(
    url: str,
    *,
    proxy_pool: ProxyPool | None = None,
    max_attempts: int = 2,
) -> Document | None:
    """Fetch and parse a WeChat Official Account article, or None on failure."""
    if not is_weixin_article_url(url):
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    opener = _build_opener(proxy_pool)

    def _do_fetch() -> Document | None:
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                import time

                time.sleep(1.0)
            try:
                html_text = _fetch_html(url, opener)
                if not html_text:
                    continue
                doc = parse_weixin_article_html(html_text, url=url)
                if doc is not None:
                    return doc
            except Exception as exc:
                last_error = exc
                logger.info(
                    "Weixin article fetch attempt %s failed for %s: %s",
                    attempt + 1,
                    url,
                    exc,
                )
        if last_error is not None:
            logger.info(
                "Weixin article fetch exhausted retries for %s: %s", url, last_error
            )
        return None

    return await asyncio.to_thread(_do_fetch)
