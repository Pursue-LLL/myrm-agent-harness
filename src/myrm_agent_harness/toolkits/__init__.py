"""Generic, framework-agnostic toolkit collection.

Each toolkit is self-contained and can be used independently.
__init__.py serves as the unified export entry for general-purpose capabilities.
Agent-callable tools are exported via dedicated xx_agent_tools.py files.

[INPUT]
- llms::llm_manager, LLMManager, ChatLiteLLM, create_litellm_model (POS: LLM manager and adapters, 100+ provider support)
- web_fetch::CrawlEngine (POS: layered crawl engine with HTTP/Browser/Stealth fallback)
- retriever_tools::RetrieverManager (POS: retriever manager class)
- web_fetch::web_fetch_tools (POS: global CrawlEngine instance)

[OUTPUT]
- llm_manager: global LLM manager singleton
- LLMManager: LLM manager class
- ChatLiteLLM: LiteLLM chat model
- create_litellm_model: LiteLLM model factory function
- CrawlEngine: layered crawl engine
- RetrieverManager: retriever manager class
- web_fetch_tools: global CrawlEngine instance

[POS]
Generic, framework-agnostic toolkit collection. No agent coupling — each toolkit is independently usable via `myrm_agent_harness.toolkits.xxx`.
- acp: ACP protocol integration (Server + Runtime)
- a2a: A2A protocol support (AgentCard discovery, Resolver, Provider Protocol)
- browser: browser automation (multi-tab, iframe traversal)
- cron: scheduled task framework (scheduling, CRUD management, incremental monitoring)
- code_execution: code execution system (Agent-in-Sandbox mode)
- file_parsers: file parsing (PDF/DOCX/Excel/Text)
- llms: LLM manager and adapters (native capability passthrough, citation extraction, image gen/edit)
- mcp: MCP protocol support
- memory: pluggable memory system (vector/relational/graph storage)
- retriever: retrieval and reranking tools
- storage: storage service
- web_fetch: layered crawl engine
- deploy: artifact deployment to hosting platforms
- web_search: web search tools
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.llms import ChatLiteLLM, LLMManager, create_litellm_model, llm_manager
    from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
    from myrm_agent_harness.toolkits.web_fetch import CrawlEngine, web_fetch_tools

__all__ = [
    "ChatLiteLLM",
    "CrawlEngine",
    "LLMManager",
    "RetrieverManager",
    "create_browser_tools",
    "create_conversation_search_tool",
    "create_cron_tools",
    "create_deploy_tool",
    "create_delegate_to_agent_tool",
    "create_litellm_model",
    "create_memory_tools",
    "create_web_fetch_tool",
    "create_web_search_tool",
    "llm_manager",
    "web_fetch_tools",
]

_LAZY_IMPORTS = {
    "llm_manager": ("myrm_agent_harness.toolkits.llms", "llm_manager"),
    "LLMManager": ("myrm_agent_harness.toolkits.llms", "LLMManager"),
    "ChatLiteLLM": ("myrm_agent_harness.toolkits.llms", "ChatLiteLLM"),
    "create_litellm_model": ("myrm_agent_harness.toolkits.llms", "create_litellm_model"),
    "CrawlEngine": ("myrm_agent_harness.toolkits.web_fetch", "CrawlEngine"),
    "RetrieverManager": ("myrm_agent_harness.toolkits.retriever.engine", "RetrieverManager"),
    "web_fetch_tools": ("myrm_agent_harness.toolkits.web_fetch", "web_fetch_tools"),
    "create_browser_tools": ("myrm_agent_harness.toolkits.browser.tools", "create_browser_tools"),
    "create_cron_tools": ("myrm_agent_harness.toolkits.cron.cron_agent_tools", "create_cron_tools"),
    "create_deploy_tool": ("myrm_agent_harness.toolkits.deploy", "create_deploy_tool"),
    "create_memory_tools": ("myrm_agent_harness.toolkits.memory.memory_agent_tools", "create_memory_tools"),
    "create_conversation_search_tool": (
        "myrm_agent_harness.toolkits.memory.conversation_search",
        "create_conversation_search_tool",
    ),
    "create_web_fetch_tool": ("myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools", "create_web_fetch_tool"),
    "create_web_search_tool": (
        "myrm_agent_harness.toolkits.web_search.web_search_agent_tools",
        "create_web_search_tool",
    ),
    "create_delegate_to_agent_tool": (
        "myrm_agent_harness.toolkits.acp.acp_agent_tools",
        "create_delegate_to_agent_tool",
    ),
}

if __debug__:
    _lazy_set = set(_LAZY_IMPORTS.keys())
    _all_set = set(__all__)
    _extra = _lazy_set - _all_set
    if _extra:
        raise RuntimeError(f"toolkits: _LAZY_IMPORTS has symbols not in __all__: {_extra}")


def __getattr__(name: str) -> object:
    """Lazy load toolkit components on first access."""
    if name in _LAZY_IMPORTS:
        from importlib import import_module

        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
