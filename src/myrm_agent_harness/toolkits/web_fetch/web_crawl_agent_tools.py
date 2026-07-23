"""Web crawl meta-tool — async deep site crawl (EXTENDED, opt-in).

Split from web_fetch_tool to keep Turn1 fetch schema minimal (prompt cache).

[INPUT]
- toolkits.web_fetch.deep_crawl::DeepCrawlPipeline
- toolkits.web_fetch.task_store::CrawlTaskStore

[OUTPUT]
- create_web_crawl_tool: LangChain tool for start/status/cancel deep crawl

[POS]
Optional LangChain adapter for site-wide recursive crawl; not part of default Agent baseline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from langchain.tools import tool

from myrm_agent_harness.utils.errors import ToolError


def _resolve_crawl_data_dir(data_dir: str | None) -> str:
    if data_dir:
        return data_dir

    from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var

    workspace_root = workspace_root_var.get().strip()
    chat_id = chat_id_var.get().strip()
    if workspace_root and chat_id:
        return f"{workspace_root}/.crawl/{chat_id}"

    return "/tmp/myrm_crawl_data"


def create_web_crawl_tool(
    *,
    allow_private_networks: bool = False,
    data_dir: str | None = None,
):
    """Create web crawl tool for recursive site crawling."""

    resolved_data_dir = data_dir

    class WebCrawlInput(BaseModel):
        operation: str = Field(
            default="start",
            description="Operation: start | status | cancel",
        )
        seed_url: str = Field(default="", description="Seed URL for start (required when operation=start)")
        max_depth: int = Field(default=3, ge=1, le=5, description="Max crawl depth (default 3)")
        max_pages: int = Field(default=100, ge=1, le=500, description="Max pages (default 100)")
        task_group_id: str = Field(default="", description="Task group id for status/cancel")
        reason: str = Field(description="Brief reason for this crawl, max 100 chars")

    tool_description = """
Recursively crawl an entire website starting from a seed URL. Pages are saved as Markdown in sandbox storage.

Operations:
- start: Begin crawl (seed_url required). Returns task_group_id immediately.
- status: Check progress (task_group_id required).
- cancel: Cancel pending tasks (task_group_id required).

After completion, use file_read_tool to read pages from the results directory.
""".strip()

    @tool("web_crawl_tool", description=tool_description, args_schema=WebCrawlInput)
    async def web_crawl_func(
        operation: str = "start",
        seed_url: str = "",
        max_depth: int = 3,
        max_pages: int = 100,
        task_group_id: str = "",
        reason: str = "",
    ) -> dict[str, str | dict[str, object]]:
        crawl_data_dir = _resolve_crawl_data_dir(resolved_data_dir)

        if operation == "start":
            if not seed_url.strip():
                raise ToolError(
                    "seed_url is required for start",
                    user_hint="Provide a valid seed URL to begin deep crawl.",
                )
            if not allow_private_networks:
                from myrm_agent_harness.core.security.guards.ssrf import validate_url_for_ssrf

                result = validate_url_for_ssrf(seed_url)
                if not result.safe:
                    raise ToolError(
                        f"URL blocked (SSRF protection): {result.error} — {seed_url}",
                        user_hint="The URL is blocked for security reasons. Use a publicly accessible URL.",
                    )
            return await _deep_crawl(
                seed_url,
                max_depth=max_depth,
                max_pages=max_pages,
                allow_private_networks=allow_private_networks,
                data_dir=crawl_data_dir,
            )

        if operation == "status":
            if not task_group_id:
                raise ToolError(
                    "task_group_id is required for status",
                    user_hint="Provide the task_group_id returned by start.",
                )
            return await _check_crawl_status(task_group_id, data_dir=crawl_data_dir)

        if operation == "cancel":
            if not task_group_id:
                raise ToolError(
                    "task_group_id is required for cancel",
                    user_hint="Provide the task_group_id returned by start.",
                )
            return await _cancel_crawl(task_group_id, data_dir=crawl_data_dir)

        raise ToolError(
            f"Unknown operation: {operation}",
            user_hint="Use operation start, status, or cancel.",
        )

    return web_crawl_func


async def _deep_crawl(
    seed_url: str,
    *,
    max_depth: int = 3,
    max_pages: int = 100,
    allow_private_networks: bool = False,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch import CrawlEngine
    from myrm_agent_harness.toolkits.web_fetch.deep_crawl import DeepCrawlPipeline
    from myrm_agent_harness.toolkits.web_fetch.rate_limiter import DomainRateLimiter
    from myrm_agent_harness.toolkits.web_fetch.robots_parser import RobotsParser
    from myrm_agent_harness.toolkits.web_fetch.task_executor import CrawlTaskExecutor
    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    base_path = Path(data_dir or _resolve_crawl_data_dir(None))
    db_path = base_path / ".crawl_tasks.db"

    store = CrawlTaskStore(db_path)
    engine = CrawlEngine(allow_private_networks=allow_private_networks)
    rate_limiter = DomainRateLimiter(default_interval=1.5, max_concurrent_per_domain=2)
    robots_parser = RobotsParser()
    executor = CrawlTaskExecutor(store, engine, rate_limiter, max_workers=5)

    pipeline = DeepCrawlPipeline(
        store=store,
        executor=executor,
        engine=engine,
        robots_parser=robots_parser,
        rate_limiter=rate_limiter,
        data_dir=base_path,
    )

    result = await pipeline.start_deep_crawl(seed_url, max_depth=max_depth, max_pages=max_pages)

    return {
        "content": (
            f"Deep crawl initiated for: {seed_url}\n"
            f"Task Group ID: {result['task_group_id']}\n"
            f"Total pages discovered: {result['total_pages']}\n"
            f"Results will be saved to: {result['result_dir']}\n\n"
            f"Use web_crawl_tool operation=status with task_group_id='{result['task_group_id']}' to monitor progress.\n"
            f"Once completed, use file_read_tool to read Markdown files from the result directory."
        ),
        "metadata": {
            "operation": "deep_crawl",
            **result,
        },
    }


async def _check_crawl_status(
    task_group_id: str,
    *,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    import json
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    db_path = Path(data_dir or _resolve_crawl_data_dir(None)) / ".crawl_tasks.db"
    if not db_path.exists():
        raise ToolError(
            f"No crawl database found at {db_path}",
            user_hint="No deep crawl tasks have been started. Start one first with operation=start.",
        )

    store = CrawlTaskStore(db_path)
    summary = store.get_group_summary(task_group_id)

    if not summary:
        raise ToolError(
            f"Task group not found: {task_group_id}",
            user_hint="The task_group_id is invalid. Check the ID returned by start.",
        )

    is_done = not store.has_pending_or_running(task_group_id)
    status = "completed" if is_done else "running"

    index_path = Path(summary.result_dir) / "_index.json"
    index_info = ""
    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        pages = index_data.get("pages", [])
        if pages:
            index_info = "\n\nCrawled pages:\n"
            for page in pages[:20]:
                index_info += f"  - {page['file']}: {page['title']} ({page['url']})\n"
            if len(pages) > 20:
                index_info += f"  ... and {len(pages) - 20} more\n"

    return {
        "content": (
            f"Deep crawl status: {status}\n"
            f"Progress: {summary.completed}/{summary.total} pages completed"
            + (f" ({summary.failed} failed)" if summary.failed else "")
            + (f" ({summary.cancelled} cancelled)" if summary.cancelled else "")
            + f"\nPending: {summary.pending}, Running: {summary.running}\n"
            f"Results directory: {summary.result_dir}"
            + index_info
        ),
        "metadata": {
            "operation": "check_crawl_status",
            "group_id": task_group_id,
            "status": status,
            "total": summary.total,
            "completed": summary.completed,
            "failed": summary.failed,
            "pending": summary.pending,
            "running": summary.running,
            "cancelled": summary.cancelled,
            "result_dir": summary.result_dir,
        },
    }


async def _cancel_crawl(
    task_group_id: str,
    *,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    db_path = Path(data_dir or _resolve_crawl_data_dir(None)) / ".crawl_tasks.db"
    if not db_path.exists():
        raise ToolError(
            f"No crawl database found at {db_path}",
            user_hint="No deep crawl tasks have been started.",
        )

    store = CrawlTaskStore(db_path)
    summary = store.get_group_summary(task_group_id)

    if not summary:
        raise ToolError(
            f"Task group not found: {task_group_id}",
            user_hint="The task_group_id is invalid.",
        )

    cancelled_count = store.cancel_group(task_group_id)

    return {
        "content": (
            f"Deep crawl cancelled: {task_group_id}\n"
            f"Cancelled {cancelled_count} pending tasks.\n"
            f"Completed pages ({summary.completed}) are preserved in: {summary.result_dir}"
        ),
        "metadata": {
            "operation": "cancel_crawl",
            "group_id": task_group_id,
            "cancelled_count": cancelled_count,
            "completed": summary.completed,
            "result_dir": summary.result_dir,
        },
    }
