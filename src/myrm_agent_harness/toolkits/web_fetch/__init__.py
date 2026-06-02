"""Web fetch toolkit.


[INPUT]
- engine::CrawlEngine, FailedResult, SuccessResult (POS: layered crawl engine with HTTP/Browser/Stealth fallback)

[OUTPUT]
- CrawlEngine: layered crawl engine (re-export)
- FailedResult: failed crawl result model (re-export)
- SuccessResult: successful crawl result model (re-export)
- web_fetch_tools: global CrawlEngine instance

[POS]
Web fetch toolkit entry point. Re-exports the core crawl engine and result types.
"""

from .engine import CrawlEngine, FailedResult, SuccessResult

web_fetch_tools = CrawlEngine()

__all__ = ["CrawlEngine", "FailedResult", "SuccessResult", "web_fetch_tools"]
