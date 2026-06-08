"""DeepCrawlRouter — Recursive site crawl via sitemap/link discovery.

Discovers pages from a seed URL using sitemap.xml (preferred) or HTML
link extraction (fallback), then enqueues them into CrawlTaskStore
for async background execution.

[INPUT]
- web_fetch.task_store::CrawlTaskStore (POS: Task persistence)
- web_fetch.robots_parser::RobotsParser, RobotsRules (POS: Robots.txt compliance)
- web_fetch.rate_limiter::DomainRateLimiter (POS: Rate limiting)
- web_fetch.task_executor::CrawlTaskExecutor (POS: Background execution)
- web_fetch.engine::CrawlEngine (POS: Core crawl engine)

[OUTPUT]
- DeepCrawlPipeline: Orchestrates full deep_crawl lifecycle

[POS]
Deep crawl orchestrator. Discovers site pages via sitemap/link extraction,
respects robots.txt, enqueues tasks, and starts background execution.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from .engine import CrawlEngine
    from .rate_limiter import DomainRateLimiter
    from .robots_parser import RobotsParser, RobotsRules
    from .task_executor import CrawlTaskExecutor
    from .task_store import CrawlTaskStore

logger = logging.getLogger(__name__)

_SITEMAP_URL_RE = re.compile(r"<loc>\s*(https?://[^<]+)\s*</loc>", re.IGNORECASE)
_HTML_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

_SKIP_EXTENSIONS = frozenset({
    ".pdf", ".zip", ".tar", ".gz", ".exe", ".dmg", ".pkg",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
})


class DeepCrawlPipeline:
    """Orchestrates the full deep_crawl lifecycle.

    1. Fetch and parse robots.txt
    2. Discover pages via sitemap.xml or HTML link extraction
    3. Filter by robots.txt rules and domain boundaries
    4. Enqueue tasks into CrawlTaskStore
    5. Start CrawlTaskExecutor for background execution
    """

    def __init__(
        self,
        store: CrawlTaskStore,
        executor: CrawlTaskExecutor,
        engine: CrawlEngine,
        robots_parser: RobotsParser,
        rate_limiter: DomainRateLimiter,
        data_dir: Path,
    ):
        self._store = store
        self._executor = executor
        self._engine = engine
        self._robots = robots_parser
        self._rate_limiter = rate_limiter
        self._data_dir = data_dir

    async def start_deep_crawl(
        self,
        seed_url: str,
        *,
        max_depth: int = 3,
        max_pages: int = 100,
    ) -> dict[str, str | int]:
        """Initiate a deep crawl from a seed URL.

        Returns immediately with task group metadata. Actual crawling
        happens in the background via CrawlTaskExecutor.

        Returns:
            Dict with group_id, status, total_pages, result_dir
        """
        parsed = urlparse(seed_url)
        domain = parsed.netloc
        base_origin = f"{parsed.scheme}://{parsed.netloc}"

        result_dir = str(self._data_dir / "crawl_results" / f"crawl_{domain}_{_short_id()}")
        group_id = self._store.create_group(
            seed_url=seed_url,
            result_dir=result_dir,
            max_depth=max_depth,
            max_pages=max_pages,
        )

        rules = await self._robots.fetch_and_parse(seed_url)

        if rules.crawl_delay is not None:
            self._rate_limiter.set_domain_interval(domain, rules.crawl_delay)

        discovered_urls = await self._discover_pages(seed_url, base_origin, rules, max_depth, max_pages)

        if discovered_urls:
            self._store.add_tasks_batch(group_id, discovered_urls)

        total = self._store.get_group_total_tasks(group_id)

        await self._executor.start_group(group_id)

        return {
            "task_group_id": group_id,
            "status": "running",
            "total_pages": total,
            "result_dir": result_dir,
            "seed_url": seed_url,
        }

    async def _discover_pages(
        self,
        seed_url: str,
        base_origin: str,
        rules: RobotsRules,
        max_depth: int,
        max_pages: int,
    ) -> list[tuple[str, int]]:
        """Discover pages using sitemap (preferred) or seed page link extraction."""
        discovered: list[tuple[str, int]] = []
        seen_urls: set[str] = set()

        if rules.sitemaps:
            for sitemap_url in rules.sitemaps:
                if len(discovered) >= max_pages:
                    break
                urls = await self._parse_sitemap(sitemap_url, base_origin, rules, max_pages - len(discovered))
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        discovered.append((url, 1))

        if not discovered:
            discovered.append((seed_url, 0))
            seen_urls.add(seed_url)

            if max_depth > 0:
                links = await self._extract_links_from_page(seed_url, base_origin, rules)
                for link in links:
                    if len(discovered) >= max_pages:
                        break
                    if link not in seen_urls:
                        seen_urls.add(link)
                        discovered.append((link, 1))

        return discovered[:max_pages]

    async def _parse_sitemap(
        self,
        sitemap_url: str,
        base_origin: str,
        rules: RobotsRules,
        limit: int,
    ) -> list[str]:
        """Parse sitemap.xml and extract valid URLs."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(sitemap_url)
                if resp.status_code != 200:
                    return []

                urls: list[str] = []
                for match in _SITEMAP_URL_RE.finditer(resp.text):
                    url = match.group(1).strip()
                    if self._is_valid_crawl_url(url, base_origin, rules):
                        urls.append(url)
                        if len(urls) >= limit:
                            break

                return urls
        except Exception as e:
            logger.warning("Failed to parse sitemap: %s — %s", sitemap_url, e)
            return []

    async def _extract_links_from_page(
        self,
        page_url: str,
        base_origin: str,
        rules: RobotsRules,
    ) -> list[str]:
        """Extract links from a page using CrawlEngine."""
        try:
            doc = await self._engine.crawl(page_url)
            if not doc:
                return []

            raw_html = doc.metadata.get("_raw_html", "")
            if not raw_html:
                text = doc.page_content
                links: list[str] = []
                for match in re.finditer(r'\[([^\]]*)\]\((https?://[^)]+)\)', text):
                    url = match.group(2)
                    if self._is_valid_crawl_url(url, base_origin, rules):
                        links.append(url)
                return links[:50]

            links = []
            for match in _HTML_LINK_RE.finditer(raw_html):
                href = match.group(1)
                url = urljoin(page_url, href)
                if self._is_valid_crawl_url(url, base_origin, rules):
                    links.append(url)
            return links[:50]

        except Exception as e:
            logger.warning("Failed to extract links: %s — %s", page_url, e)
            return []

    def _is_valid_crawl_url(self, url: str, base_origin: str, rules: RobotsRules) -> bool:
        """Check if URL is valid for crawling (same-origin, allowed, proper extension)."""
        try:
            parsed = urlparse(url)

            if not parsed.scheme or not parsed.netloc:
                return False
            if f"{parsed.scheme}://{parsed.netloc}" != base_origin:
                return False

            path = parsed.path.lower()
            ext = Path(path).suffix
            if ext in _SKIP_EXTENSIONS:
                return False

            if parsed.fragment:
                return False

            return rules.is_path_allowed(parsed.path)
        except Exception:
            return False


def _short_id() -> str:
    """Generate a short unique ID for directory naming."""
    import uuid
    return uuid.uuid4().hex[:8]
