"""Web fetch toolkit.

[INPUT]
- engine::FetchEngine, FailedResult, SuccessResult (POS: layered single-page fetch engine)

[OUTPUT]
- FetchEngine: layered fetch engine (re-export)
- FailedResult: failed fetch result model (re-export)
- SuccessResult: successful fetch result model (re-export)
- web_fetch_tools: global FetchEngine instance

[POS]
Web fetch toolkit entry point. Re-exports the core single-page fetch engine.
"""

from .engine import FailedResult, FetchEngine, SuccessResult

web_fetch_tools = FetchEngine()

__all__ = [
    "FetchEngine",
    "FailedResult",
    "SuccessResult",
    "web_fetch_tools",
]
