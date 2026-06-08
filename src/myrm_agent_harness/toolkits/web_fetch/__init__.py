"""Web fetch toolkit.


[INPUT]
- engine::CrawlEngine, FailedResult, SuccessResult (POS: layered crawl engine with HTTP/Browser/Stealth fallback)
- deep_crawl::DeepCrawlPipeline (POS: recursive site crawl orchestrator)
- task_store::CrawlTaskStore, CrawlTaskStatus, CrawlTask, CrawlTaskGroupSummary (POS: SQLite task persistence)
- task_executor::CrawlTaskExecutor (POS: background task executor)
- rate_limiter::DomainRateLimiter (POS: per-domain rate limiting)
- robots_parser::RobotsParser, RobotsRules (POS: robots.txt compliance)

[OUTPUT]
- CrawlEngine: layered crawl engine (re-export)
- FailedResult: failed crawl result model (re-export)
- SuccessResult: successful crawl result model (re-export)
- web_fetch_tools: global CrawlEngine instance
- DeepCrawlPipeline: recursive crawl orchestrator (re-export)
- CrawlTaskStore: SQLite task queue (re-export)

[POS]
Web fetch toolkit entry point. Re-exports the core crawl engine, deep crawl
pipeline, and supporting components.
"""

from .engine import CrawlEngine, FailedResult, SuccessResult

web_fetch_tools = CrawlEngine()

__all__ = [
    "CrawlEngine",
    "FailedResult",
    "SuccessResult",
    "web_fetch_tools",
]
