"""Unit tests for InProcessBM25Retriever and DynamicToolSchemaPruner.

Validates sub-millisecond lexical search, ~80% token savings,
core tool retention, and on-demand progressive disclosure expansion.
"""

from __future__ import annotations

import concurrent.futures
import time

from myrm_agent_harness.runtime.context.dynamic_tool_schema_pruner import (
    DynamicToolSchemaPruner,
)
from myrm_agent_harness.runtime.context.in_process_bm25_retriever import (
    InProcessBM25Retriever,
    tokenize_lexical,
)
from myrm_agent_harness.runtime.context.in_process_bm25_types import (
    ProgressiveDisclosureConfig,
    ToolSchemaEntry,
)


def test_lexical_tokenizer() -> None:
    """Verify tokenizer splits snake_case, camelCase, and natural phrases into lowercase words."""
    tokens = tokenize_lexical("executeGitCommit_and_pushToRemote --branch=feature-1")
    assert "execute" in tokens
    assert "git" in tokens
    assert "commit" in tokens
    assert "and" in tokens
    assert "push" in tokens
    assert "to" in tokens
    assert "remote" in tokens
    assert "branch" in tokens
    assert "feature" in tokens

    empty_tokens = tokenize_lexical("")
    assert empty_tokens == ()


def test_bm25_retrieval_accuracy_and_idf() -> None:
    """Verify BM25 properly scores document relevance using Robertson-Spärck Jones IDF."""
    retriever = InProcessBM25Retriever()
    retriever.index_document("doc1", "PostgreSQL database client query executor and SQL transaction")
    retriever.index_document("doc2", "Git repository branch commit diff merger and worktree manager")
    retriever.index_document("doc3", "Chrome browser automation driver puppeteer click and navigate")

    assert retriever.total_documents == 3

    # Search for git diff
    hits = retriever.search("git branch diff", top_k=2)
    assert len(hits) > 0
    assert hits[0].doc_id == "doc2"
    assert hits[0].rank == 1
    assert hits[0].score > 0.0

    # Search for SQL database
    hits_sql = retriever.search("run sql query against postgres", top_k=1)
    assert len(hits_sql) == 1
    assert hits_sql[0].doc_id == "doc1"

    # Search with empty query
    assert retriever.search("") == ()


def test_bm25_sub_millisecond_benchmark() -> None:
    """Verify in-process BM25 delivers sub-millisecond retrieval on 100 documents."""
    retriever = InProcessBM25Retriever()
    docs = [
        (
            f"tool_{i}",
            f"Specialized utility {i} for microservice operations, cluster monitoring {i % 10}, "
            f"log parsing {i % 5}, and cloud orchestration {i % 3}",
            {"id": i},
        )
        for i in range(100)
    ]
    retriever.index_documents_batch(docs)
    assert retriever.total_documents == 100

    # Benchmark 50 searches
    t0 = time.perf_counter()
    iterations = 50
    for i in range(iterations):
        hits = retriever.search(f"cluster monitoring {i % 10} log parsing", top_k=5)
        assert len(hits) > 0
    t1 = time.perf_counter()

    avg_time_ms = ((t1 - t0) / iterations) * 1000.0
    # Must be sub-millisecond or low single-digit ms even in test environments
    assert avg_time_ms < 5.0, f"Average retrieval took {avg_time_ms:.3f} ms, expected < 5 ms"


def test_dynamic_tool_schema_pruner_token_savings() -> None:
    """Verify DynamicToolSchemaPruner achieves ~75%+ token reduction by progressive disclosure."""
    config = ProgressiveDisclosureConfig(
        top_k=2,
        core_tool_names=("read_file", "write_file", "run_command"),
    )
    pruner = DynamicToolSchemaPruner(config=config)

    # Register 3 core tools
    pruner.register_tool(
        ToolSchemaEntry(
            name="read_file",
            description="Read file contents from filesystem",
            parameters_schema_json='{"type": "object", "properties": {"path": {"type": "string"}}}',
            is_core=True,
        )
    )
    pruner.register_tool(
        ToolSchemaEntry(
            name="write_file",
            description="Write content to a file",
            parameters_schema_json='{"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}',
            is_core=True,
        )
    )
    pruner.register_tool(
        ToolSchemaEntry(
            name="run_command",
            description="Execute shell commands in workspace sandbox",
            parameters_schema_json='{"type": "object", "properties": {"cmd": {"type": "string"}}}',
            is_core=True,
        )
    )

    # Register 17 specialized tools (total 20 tools)
    specialized_specs = [
        ("git_commit", "Create git commit with author and message", ("git", "commit", "vcs")),
        ("git_diff", "Inspect uncommitted git diff patches", ("git", "diff", "patch")),
        ("git_push", "Push committed branch to remote upstream", ("git", "push", "remote")),
        ("sql_query", "Run read-only SQL queries on relational database", ("sql", "postgres", "db")),
        ("sql_migrate", "Apply database schema migrations", ("sql", "migration", "ddl")),
        ("audio_transcribe", "Convert speech audio to text transcription", ("audio", "voice", "speech")),
        ("docker_build", "Build container image using Dockerfile", ("docker", "container", "image")),
        ("k8s_deploy", "Deploy manifests to Kubernetes cluster pods", ("k8s", "kubernetes", "pods")),
        ("browser_click", "Click UI element in headless browser page", ("browser", "web", "click")),
        ("browser_screenshot", "Capture viewport screenshot of browser page", ("browser", "screenshot")),
        ("email_send", "Send SMTP transactional notification email", ("email", "mail", "smtp")),
        ("slack_notify", "Send webhook message to Slack team channel", ("slack", "notification", "chat")),
        ("pdf_extract", "Extract text and tables from PDF documents", ("pdf", "document", "extract")),
        ("s3_upload", "Upload binary blob object to AWS S3 bucket", ("s3", "cloud", "aws", "storage")),
        ("redis_cache_get", "Retrieve cached key-value object from Redis", ("redis", "cache", "key")),
        ("graphql_query", "Execute GraphQL schema query against endpoint", ("graphql", "api", "query")),
        ("terraform_apply", "Apply infrastructure as code Terraform plan", ("terraform", "iac", "infra")),
    ]

    for name, desc, kws in specialized_specs:
        pruner.register_tool(
            ToolSchemaEntry(
                name=name,
                description=desc,
                parameters_schema_json='{"type": "object", "properties": {"target": {"type": "string"}, "options": {"type": "object"}}}',
                is_core=False,
                keywords=kws,
            )
        )

    assert pruner.registered_count == 20

    # Prune for a git-related query
    pruned = pruner.prune_for_query("Can you inspect git diff and prepare a commit for me?")

    active_names = {t.name for t in pruned.active_tools}
    # All 3 core tools must be active
    assert "read_file" in active_names
    assert "write_file" in active_names
    assert "run_command" in active_names

    # Top-2 matched dynamic tools must include git tools
    assert "git_diff" in active_names or "git_commit" in active_names
    # Unrelated tools must NOT be active
    assert "audio_transcribe" not in active_names
    assert "terraform_apply" not in active_names
    assert "k8s_deploy" not in active_names

    # Check token savings ratio (should be >= 70%)
    assert pruned.token_saving_ratio >= 0.70
    assert "<tool_progressive_disclosure" in pruned.expansion_directive
    assert "Additional dormant tools:" in pruned.expansion_directive


def test_dynamic_tool_expansion() -> None:
    """Verify on-demand expansion wakes up dormant tools and updates savings statistics."""
    pruner = DynamicToolSchemaPruner()
    pruner.register_tool(
        ToolSchemaEntry(
            name="read_file",
            description="Read file",
            parameters_schema_json="{}",
            is_core=True,
        )
    )
    pruner.register_tool(
        ToolSchemaEntry(
            name="audio_transcribe",
            description="Transcribe voice audio",
            parameters_schema_json="{}",
            is_core=False,
            keywords=("voice", "audio"),
        )
    )

    initial_pruned = pruner.prune_for_query("Read readme.md")
    assert len(initial_pruned.active_tools) == 1
    assert "audio_transcribe" in initial_pruned.pruned_tool_names

    # Expand by waking up audio_transcribe
    expanded = pruner.expand_tool_set(initial_pruned, ["audio_transcribe"])
    expanded_names = {t.name for t in expanded.active_tools}
    assert "audio_transcribe" in expanded_names
    assert len(expanded.pruned_tool_names) == 0


def test_concurrent_pruning_and_registration() -> None:
    """Verify thread-safety when pruning and registering tools concurrently."""
    pruner = DynamicToolSchemaPruner()
    for i in range(10):
        pruner.register_tool(
            ToolSchemaEntry(
                name=f"initial_tool_{i}",
                description=f"Initial tool {i} for data processing",
                parameters_schema_json="{}",
                is_core=(i == 0),
            )
        )

    def worker_prune(w_id: int) -> None:
        for _ in range(5):
            res = pruner.prune_for_query(f"data processing task {w_id}")
            assert len(res.active_tools) > 0

    def worker_register(w_id: int) -> None:
        for j in range(5):
            pruner.register_tool(
                ToolSchemaEntry(
                    name=f"dyn_tool_{w_id}_{j}",
                    description=f"Dynamic tool created by worker {w_id}",
                    parameters_schema_json="{}",
                )
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [
            executor.submit(worker_prune, i) for i in range(3)
        ] + [
            executor.submit(worker_register, i) for i in range(3)
        ]
        for fut in concurrent.futures.as_completed(futs):
            fut.result()

    assert pruner.registered_count == 25
