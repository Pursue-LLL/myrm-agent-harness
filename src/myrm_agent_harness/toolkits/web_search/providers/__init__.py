"""Search provider adapters and orchestration.

[INPUT]
- providers.chain::search_provider_chain (POS: Priority-ordered provider chain runner)
- providers.litellm_search::LiteLLMSearch (POS: LiteLLM unified search client, loaded on first access)
- providers.web_searcher::WebSearcher, SearchServiceConfig, SearchServiceType (POS: Web search orchestrator)

[OUTPUT]
- Re-exports: WebSearcher, SearchServiceConfig, SearchServiceType, LiteLLMSearch, search_provider_chain

[POS]
Subpackage entry for search provider adapters and orchestration.
"""

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.web_search.providers.chain import search_provider_chain
from myrm_agent_harness.toolkits.web_search.providers.github_code_search import (
    build_github_code_query,
    search_github_code,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
    SearchServiceConfig,
    SearchServiceType,
    WebSearcher,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.providers.litellm_search import LiteLLMSearch

__all__ = [
    "LiteLLMSearch",
    "SearchServiceConfig",
    "SearchServiceType",
    "WebSearcher",
    "build_github_code_query",
    "search_github_code",
    "search_provider_chain",
]


def __getattr__(name: str) -> object:
    """Load LiteLLMSearch on first access so importing the providers never pulls in litellm."""
    if name == "LiteLLMSearch":
        from myrm_agent_harness.toolkits.web_search.providers.litellm_search import LiteLLMSearch

        globals()[name] = LiteLLMSearch
        return LiteLLMSearch
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
