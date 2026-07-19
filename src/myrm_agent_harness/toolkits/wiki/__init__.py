"""LLM-Wiki Knowledge Base Toolkit (Karpathy Architecture).

A framework-level toolkit for building self-evolving knowledge bases.
LLM acts as a "compiler" to maintain structured markdown wikis.


[INPUT]
- wiki.core::WikiStructure, WikiConfig (POS: wiki file system abstraction and configuration)
- wiki.compiler::WikiCompiler (POS: LLM-powered wiki compilation engine)
- wiki.query::WikiQueryEngine (POS: wiki query and enhancement engine)
- wiki.linter::WikiLinter (POS: wiki health check and maintenance)
- wiki.tools::create_wiki_tools (POS: LangChain tool integration)

[OUTPUT]
- WikiStructure: file system abstraction for wiki
- WikiCompiler: LLM-powered compilation engine
- WikiQueryEngine: query and enhance knowledge base
- WikiLinter: health checks and maintenance
- WikiConfig: wiki configuration
- create_wiki_tools: LangChain agent tool factory (ingest, query)
- create_wiki_admin_tools: compile/maintain tools for REST and tests

[POS]
Wiki toolkit entry point. Provides a self-evolving knowledge base framework using LLM
as a "compiler" for structured markdown wikis with ingest/query agent tools plus REST-only compile/maintain.

## Architecture

4-stage cycle:
1. **Ingest**: Raw documents (PDFs, markdown, web) → raw/
2. **Compile**: LLM extracts concepts → generates wiki articles
3. **Query & Enhance**: Answer questions → archive valuable results
4. **Lint & Maintain**: Health checks → auto-repair → discover connections

## Core Components

- WikiStructure: File system abstraction
- WikiCompiler: LLM-powered compilation engine
- WikiQueryEngine: Query and enhance knowledge base
- WikiLinter: Health checks and maintenance
- Wiki Tools: LangChain agent tools (ingest, query); admin compile/maintain via REST

## Quick Start

```python
from langchain_openai import ChatOpenAI
from myrm_agent_harness.toolkits.wiki import (
    WikiStructure,
    WikiCompiler,
    WikiQueryEngine,
    WikiLinter,
    WikiConfig,
    create_wiki_tools,
)

# Setup
llm = ChatOpenAI(model="gpt-4")
structure = WikiStructure(base_dir="./my-wiki")
config = WikiConfig()

# Initialize components
compiler = WikiCompiler(llm, structure, config)
# search_fn: optional SemanticSearchFn for enhanced search (e.g. BM25/vector)
# When enable_semantic_search=True and search_fn is provided, uses it;
# otherwise falls back to keyword matching.
query_engine = WikiQueryEngine(llm, structure, config, search_fn=my_search_fn)
linter = WikiLinter(llm, structure, config)

# Create tools for Agent
tools = create_wiki_tools(compiler, query_engine, linter, structure)

# Now Agent can use: wiki_ingest, wiki_compile, wiki_query, wiki_maintain
```

## Design Principles

- **Framework-level**: Zero dependencies on business logic
- **Multi-tenant ready**: Each user gets isolated wiki (via base_dir)
- **Configurable**: WikiConfig for all behavior switches
- **Pluggable search**: Inject custom search via SemanticSearchFn (BM25, vector, hybrid)
- **Observable**: EventLog integration for statistics
- **Parallel-optimized**: 10x faster compilation with concurrency
"""

from .core.config import WikiCompileConfig, WikiConfig, WikiQueryConfig
from .core.structure import WikiStructure
from .core.types import (
    CompileResult,
    ConceptInfo,
    LintIssue,
    LintResult,
    QueryResult,
    WikiArticle,
    WikiMetadata,
)
from .maintenance.linter import WikiLinter
from .pipeline.compiler import WikiCompiler
from .pipeline.pending import WikiPendingEditsManager
from .pipeline.queue import WikiIngestionQueue
from .retrieval.query import SemanticSearchFn, WikiQueryEngine
from .wiki_agent_tools import create_wiki_admin_tools, create_wiki_tools

__all__ = [
    "CompileResult",
    "ConceptInfo",
    "LintIssue",
    "LintResult",
    "QueryResult",
    "SemanticSearchFn",
    "WikiArticle",
    "WikiCompileConfig",
    "WikiCompiler",
    "WikiConfig",
    "WikiIngestionQueue",
    "WikiLinter",
    "WikiMetadata",
    "WikiPendingEditsManager",
    "WikiQueryConfig",
    "WikiQueryEngine",
    "WikiStructure",
    "create_wiki_admin_tools",
    "create_wiki_tools",
]
