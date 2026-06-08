"""CrawlTaskExecutor — Background async worker for deep_crawl task execution.

Consumes tasks from CrawlTaskStore, executes them via CrawlEngine,
persists results to filesystem, and emits progress events.

[INPUT]
- web_fetch.engine::CrawlEngine (POS: Core crawl engine)
- web_fetch.task_store::CrawlTaskStore, CrawlTaskStatus (POS: Task persistence)
- web_fetch.rate_limiter::DomainRateLimiter (POS: Per-domain rate limiting)
- utils.event_utils::dispatch_custom_event (POS: Event dispatch)

[OUTPUT]
- CrawlTaskExecutor: Background executor consuming crawl tasks

[POS]
Background async worker pool for deep_crawl pipeline. Consumes tasks from
SQLite store, crawls via CrawlEngine with rate limiting, persists results
as Markdown files, generates _index.json, and emits progress events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .engine import CrawlEngine
    from .rate_limiter import DomainRateLimiter
    from .task_store import CrawlTaskStore

logger = logging.getLogger(__name__)

_FILENAME_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _url_to_filename(url: str, index: int) -> str:
    """Convert URL to safe filename."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "index"
    safe = _FILENAME_UNSAFE.sub("_", path)
    if len(safe) > 80:
        safe = safe[:80]
    return f"{index:04d}_{safe}.md"


class CrawlTaskExecutor:
    """Background executor for deep_crawl task groups.

    Runs as asyncio tasks, consuming pending tasks from the store,
    respecting rate limits, and persisting results to disk.
    """

    def __init__(
        self,
        store: CrawlTaskStore,
        engine: CrawlEngine,
        rate_limiter: DomainRateLimiter,
        *,
        max_workers: int = 5,
    ):
        self._store = store
        self._engine = engine
        self._rate_limiter = rate_limiter
        self._max_workers = max_workers
        self._active_groups: dict[str, asyncio.Task[None]] = {}

    async def start_group(self, group_id: str) -> None:
        """Start background execution for a task group."""
        if group_id in self._active_groups:
            return

        task = asyncio.create_task(self._execute_group(group_id))
        self._active_groups[group_id] = task

        def _cleanup(t: asyncio.Task[None]) -> None:
            self._active_groups.pop(group_id, None)

        task.add_done_callback(_cleanup)

    async def _execute_group(self, group_id: str) -> None:
        """Execute all tasks in a group with controlled concurrency."""
        sem = asyncio.Semaphore(self._max_workers)
        workers: list[asyncio.Task[None]] = []
        completed_count = 0
        file_index = 0

        result_dir = self._get_result_dir(group_id)
        if result_dir:
            Path(result_dir).mkdir(parents=True, exist_ok=True)

        while True:
            task = self._store.claim_next_pending(group_id)
            if task is None:
                if workers:
                    await asyncio.gather(*workers, return_exceptions=True)
                    workers.clear()
                    continue
                break

            file_index += 1
            current_index = file_index

            async def _process(t=task, idx=current_index) -> None:
                nonlocal completed_count
                async with sem:
                    await self._execute_single_task(t, group_id, idx)
                    completed_count += 1
                    await self._emit_progress(group_id)

            worker = asyncio.create_task(_process())
            workers.append(worker)

            if len(workers) >= self._max_workers:
                done, pending = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
                workers = list(pending)

        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

        await self._generate_index(group_id)
        await self._emit_progress(group_id, final=True)
        logger.info("Deep crawl group completed: %s (%d pages)", group_id, completed_count)

    async def _execute_single_task(self, task, group_id: str, file_index: int) -> None:
        """Execute a single crawl task with rate limiting."""
        from .task_store import CrawlTask

        assert isinstance(task, CrawlTask)
        domain = urlparse(task.url).netloc

        try:
            await self._rate_limiter.acquire(domain)
            try:
                doc = await self._engine.crawl(task.url)
            finally:
                self._rate_limiter.release(domain)

            if doc is None:
                self._store.mark_failed(task.task_id, "Crawl returned no content")
                return

            result_dir = self._get_result_dir(group_id)
            if not result_dir:
                self._store.mark_failed(task.task_id, "No result directory")
                return

            filename = _url_to_filename(task.url, file_index)
            filepath = Path(result_dir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            title = doc.metadata.get("title", "")
            header = f"# {title}\n\n> Source: {task.url}\n\n---\n\n" if title else f"> Source: {task.url}\n\n---\n\n"
            filepath.write_text(header + doc.page_content, encoding="utf-8")

            self._store.mark_completed(task.task_id, str(filepath))

            self._discover_and_enqueue_links(doc, task, group_id)

        except Exception as e:
            logger.warning("Task failed: %s — %s", task.url, e)
            self._store.mark_failed(task.task_id, str(e)[:500])

    def _discover_and_enqueue_links(self, doc, task, group_id: str) -> None:
        """Extract links from crawled page and enqueue new tasks for deeper crawling."""
        if self._store.is_group_cancelled(group_id):
            return

        from .url_normalizer import normalize_url

        max_depth = self._store.get_group_max_depth(group_id)
        if task.depth >= max_depth:
            return

        max_pages = self._store.get_group_max_pages(group_id)
        current_total = self._store.get_group_total_tasks(group_id)
        if current_total >= max_pages:
            return

        parsed_base = urlparse(task.url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        links: list[str] = []
        content = doc.page_content
        for match in re.finditer(r'\[([^\]]*)\]\((https?://[^)]+)\)', content):
            url = match.group(2)
            parsed = urlparse(url)
            if f"{parsed.scheme}://{parsed.netloc}" == base_origin:
                normalized = normalize_url(url)
                links.append(normalized)

        if not links:
            return

        budget = max_pages - current_total
        new_tasks = [(url, task.depth + 1) for url in links[:budget]]
        if new_tasks:
            self._store.add_tasks_batch(group_id, new_tasks)

    def _get_result_dir(self, group_id: str) -> str | None:
        """Get result directory for a group."""
        summary = self._store.get_group_summary(group_id)
        return summary.result_dir if summary else None

    async def _emit_progress(self, group_id: str, *, final: bool = False) -> None:
        """Emit crawl progress event for frontend consumption."""
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            summary = self._store.get_group_summary(group_id)
            if not summary:
                return

            await dispatch_custom_event(
                "agent_status",
                {
                    "step_key": "crawl_task_progress",
                    "status": "completed" if final else "running",
                    "items": [
                        {
                            "text": (
                                f"Deep crawl {'completed' if final else 'in progress'}: "
                                f"{summary.completed}/{summary.total} pages"
                                + (f" ({summary.failed} failed)" if summary.failed else "")
                            )
                        }
                    ],
                    "metadata": {
                        "type": "deep_crawl_progress",
                        "group_id": group_id,
                        "total": summary.total,
                        "completed": summary.completed,
                        "failed": summary.failed,
                        "pending": summary.pending,
                        "running": summary.running,
                        "final": final,
                    },
                },
            )
        except Exception as e:
            logger.debug("Failed to emit progress event: %s", e)

    async def _generate_index(self, group_id: str) -> None:
        """Generate _index.json with metadata for all crawled pages."""
        result_dir = self._get_result_dir(group_id)
        if not result_dir:
            return

        result_path = Path(result_dir)
        index_entries: list[dict[str, str | int]] = []

        for md_file in sorted(result_path.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            title = ""
            url = ""
            for line in lines[:5]:
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("> Source: "):
                    url = line[len("> Source: "):].strip()

            index_entries.append({
                "file": md_file.name,
                "url": url,
                "title": title,
                "word_count": len(content.split()),
            })

        index_path = result_path / "_index.json"
        summary = self._store.get_group_summary(group_id)

        index_data = {
            "group_id": group_id,
            "total_pages": len(index_entries),
            "completed": summary.completed if summary else len(index_entries),
            "failed": summary.failed if summary else 0,
            "generated_at": time.time(),
            "pages": index_entries,
        }

        index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Generated _index.json: %s (%d pages)", index_path, len(index_entries))
