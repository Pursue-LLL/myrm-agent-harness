# [INPUT]: HydrationDecision, HydrationMode, JITToolHydrationConfig, LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite, PostExecutionToolDehydrator, ToolSchemaDescriptor, VirtualCatalogIndex, VirtualToolCatalogIndexer
# [OUTPUT]: test_low_context_jit_tool_hydration_suite.py
# [POS]: tests/agent/context_management/test_low_context_jit_tool_hydration_suite.py

"""Comprehensive unit tests for LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite.

Verifies:
1. Ultra-compact virtual catalog indexing and high-ratio schema compression (>90% savings).
2. Context-adaptive mode resolution (<=64k triggers JIT hydration, >128k enables full catalog).
3. Intent-driven JIT hydration matching tool names and intent keywords from conversation turns.
4. Per-turn max hydration ceiling enforcing bounded schema exposure.
5. Post-execution dehydration and schema garbage collection reclaiming temporary mounts.
6. Unified end-to-end facade orchestration and session reset.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.jit_tool_hydration import (
    HydrationDecision,
    HydrationMode,
    JITSchemaHydrationEngine,
    JITToolHydrationConfig,
    LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite,
    PostExecutionToolDehydrator,
    ToolSchemaDescriptor,
    VirtualCatalogIndex,
    VirtualToolCatalogIndexer,
)


def _make_sample_tool(
    name: str,
    summary: str,
    tokens: int = 500,
    keywords: tuple[str, ...] = (),
) -> ToolSchemaDescriptor:
    return ToolSchemaDescriptor(
        name=name,
        short_summary=summary,
        schema_payload={
            "name": name,
            "type": "function",
            "description": f"Extended description for {name}",
        },
        estimated_tokens=tokens,
        intent_keywords=keywords,
    )


def test_virtual_tool_catalog_indexing_and_compression() -> None:
    """Verifies that virtual catalog compresses multiple tools into a compact tag with high savings."""
    indexer = VirtualToolCatalogIndexer(char_to_token_ratio=4.0)
    tools = [
        _make_sample_tool("bash", "run shell command", tokens=450),
        _make_sample_tool("file_read", "read file contents", tokens=380),
        _make_sample_tool("file_write", "modify or write files", tokens=420),
        _make_sample_tool("git", "version control actions", tokens=600),
        _make_sample_tool("web_search", "search the internet", tokens=550),
        _make_sample_tool("database_query", "query sqlite or postgres", tokens=700),
    ]

    total_full_tokens = indexer.calculate_full_schemas_token_cost(tools)
    assert total_full_tokens == 3100

    catalog = indexer.compile_catalog(tools, unhydrated_only=False)
    assert catalog.total_tools_count == 6
    assert len(catalog.tool_names) == 6
    assert "<virtual_tool_catalog count=\"6\">" in catalog.catalog_text
    assert "bash(run shell command)" in catalog.catalog_text

    # Verify that virtual catalog consumes far fewer tokens than full schemas (<150 vs 3100)
    assert catalog.estimated_catalog_tokens < 150
    savings_ratio = (total_full_tokens - catalog.estimated_catalog_tokens) / total_full_tokens
    assert savings_ratio > 0.90  # Greater than 90% savings


def test_mode_resolution_context_adaptive() -> None:
    """Verifies adaptive mode resolution based on model context window."""
    config = JITToolHydrationConfig(lean_context_threshold=65536)
    engine = JITSchemaHydrationEngine(config)

    engine.register_tool(_make_sample_tool("bash", "shell", tokens=400))
    engine.register_tool(_make_sample_tool("browser", "web view", tokens=600))

    # 1. 32k or 64k model -> JIT_HYDRATION mode
    dec_lean = engine.resolve_hydration(
        recent_prompts=["hello"],
        model_context_window=32768,
    )
    assert dec_lean.mode == HydrationMode.JIT_HYDRATION
    assert dec_lean.savings_percentage > 0.0

    # 2. 200k model -> FULL_CATALOG mode
    dec_full = engine.resolve_hydration(
        recent_prompts=["hello"],
        model_context_window=200000,
    )
    assert dec_full.mode == HydrationMode.FULL_CATALOG
    assert dec_full.hydrated_tools_count == 2
    assert dec_full.estimated_tokens_saved == 0

    # 3. Explicit override
    dec_override = engine.resolve_hydration(
        recent_prompts=["hello"],
        mode_override=HydrationMode.ALWAYS_LEAN,
        model_context_window=200000,
    )
    assert dec_override.mode == HydrationMode.ALWAYS_LEAN


def test_intent_driven_jit_hydration() -> None:
    """Verifies that intent keywords and tool mentions selectively hydrate schemas."""
    config = JITToolHydrationConfig(
        lean_context_threshold=65536,
        core_tools_whitelist=("bash", "file_read"),
    )
    engine = JITSchemaHydrationEngine(config)

    tools = [
        _make_sample_tool("bash", "run shell", tokens=300),
        _make_sample_tool("file_read", "read file", tokens=300),
        _make_sample_tool("git", "git ops", tokens=500, keywords=("commit", "branch", "diff")),
        _make_sample_tool("web_search", "search web", tokens=500, keywords=("google", "look up online")),
        _make_sample_tool("sql_runner", "execute sql", tokens=600, keywords=("database", "select from")),
    ]
    engine.register_tools(tools)

    # Turn A: Prompt requests git status and commit
    prompt_a = ["I need to check the git status and create a commit for this feature."]
    dec_a = engine.resolve_hydration(recent_prompts=prompt_a, model_context_window=32768)

    # Core tools (bash, file_read) + matched tool (git) must be hydrated
    assert "bash" in dec_a.active_tool_names
    assert "file_read" in dec_a.active_tool_names
    assert "git" in dec_a.active_tool_names
    # sql_runner and web_search remain unhydrated in the catalog
    assert "sql_runner" not in dec_a.active_tool_names
    assert "web_search" not in dec_a.active_tool_names
    assert "sql_runner" in dec_a.virtual_catalog_header

    # Turn B: Prompt mentions database lookup keyword
    prompt_b = ["Can you inspect the database and select from customers table?"]
    dec_b = engine.resolve_hydration(recent_prompts=prompt_b, model_context_window=32768)
    assert "sql_runner" in dec_b.active_tool_names


def test_max_hydrated_tools_cap() -> None:
    """Verifies that per-turn hydration respects max_hydrated_tools_per_turn ceiling."""
    config = JITToolHydrationConfig(
        max_hydrated_tools_per_turn=3,
        core_tools_whitelist=("bash",),
    )
    engine = JITSchemaHydrationEngine(config)

    # Register 6 tools
    for name in ["tool_1", "tool_2", "tool_3", "tool_4", "tool_5"]:
        engine.register_tool(_make_sample_tool(name, f"desc for {name}", tokens=300))
    engine.register_tool(_make_sample_tool("bash", "shell", tokens=300))

    # Prompt requests all tools
    all_prompt = ["Please use tool_1 tool_2 tool_3 tool_4 and tool_5"]
    dec = engine.resolve_hydration(recent_prompts=all_prompt, model_context_window=32768)

    # Must not exceed max_hydrated_tools_per_turn (3)
    assert len(dec.active_tool_names) == 3
    assert "bash" in dec.active_tool_names


def test_post_execution_dehydration_and_gc() -> None:
    """Verifies that dehydrator reclaims temporary schemas after turn completion while preserving core."""
    config = JITToolHydrationConfig(core_tools_whitelist=("bash", "file_read"))
    dehydrator = PostExecutionToolDehydrator(config)
    session_id = "test-session-xyz"

    # Mark tools hydrated during active turn
    dehydrator.mark_tools_hydrated(session_id, ["bash", "file_read", "git", "database_query"])
    assert len(dehydrator.get_active_hydrated_tools(session_id)) == 4

    # Record turn savings
    dehydrator.record_turn_savings(session_id, tokens_saved=1800)
    assert dehydrator.get_cumulative_savings(session_id) == 1800

    # Turn completes -> trigger dehydration
    pruned = dehydrator.dehydrate_after_turn(session_id, preserve_core=True)
    assert set(pruned) == {"git", "database_query"}

    # Core tools remain mounted
    remaining = dehydrator.get_active_hydrated_tools(session_id)
    assert set(remaining) == {"bash", "file_read"}

    # Session clear
    dehydrator.clear_session(session_id)
    assert dehydrator.get_active_hydrated_tools(session_id) == ()
    assert dehydrator.get_cumulative_savings(session_id) == 0


def test_facade_end_to_end_and_session_reset() -> None:
    """Verifies complete end-to-end flow through LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite."""
    suite = LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite(
        JITToolHydrationConfig(
            lean_context_threshold=65536,
            core_tools_whitelist=("bash", "file_read"),
            max_hydrated_tools_per_turn=4,
        )
    )

    # Register tool inventory
    tools = [
        _make_sample_tool("bash", "shell execution", tokens=400),
        _make_sample_tool("file_read", "read file", tokens=300),
        _make_sample_tool("git", "vcs tools", tokens=600, keywords=("git", "repo")),
        _make_sample_tool("docker", "container management", tokens=700, keywords=("docker", "image")),
        _make_sample_tool("slack", "send message", tokens=500, keywords=("slack", "channel")),
    ]
    suite.register_tools(tools)
    assert suite.registered_tools_count == 5

    session_id = "agent-conv-101"

    # 1. Turn 1: User asks for docker status
    dec1 = suite.resolve_turn_tools(
        session_id=session_id,
        recent_prompts=["Please check the docker containers running"],
        model_context_window=32768,
    )
    assert "docker" in dec1.active_tool_names
    assert "bash" in dec1.active_tool_names
    assert dec1.estimated_tokens_saved > 0

    active_t1 = suite.get_active_hydrated_tools(session_id)
    assert "docker" in active_t1

    # 2. Turn 1 completes: Dehydrate
    pruned_t1 = suite.dehydrate_turn(session_id)
    assert "docker" in pruned_t1

    # Active set back to core tools
    active_after_t1 = suite.get_active_hydrated_tools(session_id)
    assert "docker" not in active_after_t1
    assert "bash" in active_after_t1

    # 3. Cumulative savings tracked
    assert suite.get_cumulative_savings(session_id) > 0

    # 4. Reset clears session
    suite.reset_session(session_id)
    assert suite.get_active_hydrated_tools(session_id) == ()
    assert suite.get_cumulative_savings(session_id) == 0
