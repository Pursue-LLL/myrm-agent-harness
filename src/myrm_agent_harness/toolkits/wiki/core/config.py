"""Wiki configuration for LLM-Wiki Knowledge Base.

[INPUT]
dataclasses::dataclass, field (POS: standard library dataclass definition)
typing::Literal (POS: standard library type hints)

[OUTPUT]
WikiConfig: Wiki overall configuration class
WikiCompileConfig: compilation strategy configuration class
WikiQueryConfig: query strategy configuration class

[POS]
Wiki configuration center. Defines Wiki behavior configuration (compilation strategy, parallel
processing, auto-archiving, semantic search, version control, etc.), supporting framework-level
parameterized control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class WikiConfig:
    """
    Configuration for LLM-Wiki Knowledge Base (Karpathy architecture).

    Attributes:
        llm_model: LLM model for wiki compilation and maintenance (default: claude-sonnet-4.5)
        compile_strategy: Compilation strategy (incremental/full/lazy)
            - incremental: Only compile new/changed documents (default, 10x faster)
            - full: Recompile all documents (for major refactoring)
            - lazy: Compile on first query (on-demand)
        purpose: Knowledge base direction/scope description. Guides LLM during compilation and
            query to stay focused on the defined domain (e.g., "AI/ML research papers")
        auto_archive_enabled: Enable automatic archiving from Memory to Wiki
        auto_archive_min_turns: Minimum conversation turns to trigger auto-archive (default: 10)
        max_concepts_per_doc: Maximum concepts to extract per document (prevent explosion)
        enable_semantic_search: Enable semantic search in addition to keyword search
        enable_backlinks: Generate backlinks and cross-references
        enable_version_control: Enable Git version control for wiki articles
        parallel_compilation: Enable parallel document compilation (10x faster for batch)
        max_parallel_workers: Maximum parallel workers for compilation
        enable_statistics: Track wiki usage statistics (query frequency, hot concepts)
        enable_auto_maintenance: Enable automatic wiki maintenance (lint + repair)
        maintenance_interval_hours: Hours between automatic maintenance runs
    """

    llm_model: str = "claude-sonnet-4.5"
    compile_strategy: Literal["incremental", "full", "lazy"] = "incremental"
    purpose: str = ""
    auto_archive_enabled: bool = True
    auto_archive_min_turns: int = 10
    max_concepts_per_doc: int = 20
    enable_semantic_search: bool = True
    enable_hybrid_search: bool = True
    rrf_k: int = 60
    enable_backlinks: bool = True
    enable_version_control: bool = False
    parallel_compilation: bool = True
    max_parallel_workers: int = 4
    enable_statistics: bool = True
    enable_auto_maintenance: bool = True
    maintenance_interval_hours: int = 24


@dataclass(frozen=True, slots=True)
class WikiCompileConfig:
    """
    Compilation-specific configuration.

    Attributes:
        extract_concepts_prompt_template: Prompt template for concept extraction
        generate_article_prompt_template: Prompt template for article generation
        min_concept_mentions: Minimum mentions to consider a concept (avoid noise)
        max_article_length: Maximum article length in characters
        enable_example_generation: Generate usage examples in concept articles
        enable_code_snippets: Include code snippets in technical articles
    """

    extract_concepts_prompt_template: str = field(
        default=(
            "Extract key concepts from the following document. Return a JSON array of objects.\n"
            "Each object MUST have these fields:\n"
            '- "name": concept name with logical folder path (e.g., "Programming/Rust/Ownership")\n'
            '- "definition": brief definition of the concept\n'
            '- "related_concepts": array of related concept names from the same document\n'
            "CRITICAL: The concept 'name' MUST include a logical folder path for categorization.\n"
            "Use forward slashes '/' for paths. If no path is obvious, use 'Uncategorized/ConceptName'.\n"
            "Output ONLY the JSON array, no extra text."
        )
    )
    generate_article_prompt_template: str = field(
        default=(
            "Generate a comprehensive wiki article for the concept: {concept_name}\n\n"
            "{purpose_context}"
            "Based on these source documents (note the folder path as context):\n{source_docs}\n\n"
            "CRITICAL FORMATTING RULES:\n"
            "1. You MUST output strictly in Obsidian-compatible Markdown format.\n"
            "2. Enclose any mentioned related entities or concepts in [[Wikilinks]].\n"
            "3. Include a YAML frontmatter block at the top with relevant metadata "
            "(aliases, tags, sources: list of source file paths).\n"
            "4. The article MUST be strictly divided into two main sections:\n"
            "   - '## Compiled Truth': The most up-to-date, accurate summary, definitions, and conclusions.\n"
            "   - '## Timeline': A chronological log of evidence, events, or source excerpts proving the truth.\n"
            "5. NEVER paraphrase numbers, percentages, dates, or proper nouns from sources. "
            "Quote them exactly as they appear.\n"
            "6. For key facts, annotate provenance inline: (source: filename.md L42-45).\n"
            "7. Where appropriate, use rich visual elements to maximize information density:\n"
            "   - Use Mermaid diagrams (```mermaid) for workflows, architectures, and relationships.\n"
            "   - Use GFM tables for comparisons, feature matrices, and structured data.\n"
            "   - Use fenced code blocks with language tags for code examples.\n"
            "Do not output any reasoning, only the final markdown file content."
        )
    )
    min_concept_mentions: int = 2
    max_article_length: int = 5000
    enable_example_generation: bool = True
    enable_code_snippets: bool = True
    require_approval: bool = True  # HITL for new wiki edits


@dataclass(frozen=True, slots=True)
class WikiQueryConfig:
    """
    Query-specific configuration.

    Attributes:
        auto_enhance_enabled: Enable automatic enhancement (archive query results)
        min_query_quality_score: Minimum quality score to trigger enhancement (0-1)
        max_context_articles: Maximum articles to load as context
        enable_related_concepts: Show related concepts in query results
    """

    auto_enhance_enabled: bool = True
    min_query_quality_score: float = 0.7
    max_context_articles: int = 5
    enable_related_concepts: bool = True
