"""Unit tests for Subagent Workspace Context Inheritance & Prompt Enrichment (Item 56)."""

from pathlib import Path

from myrm_agent_harness.agent.sub_agents.workspace_inheritance import (
    ContextSourceType,
    RulePriority,
    SubagentRole,
    SubagentWorkspaceContextEnricher,
    WorkspaceInheritanceConfig,
)


def test_default_fallback_invariants_generation() -> None:
    """Verify fallback baseline invariants when workspace has no physical rule files."""
    enricher = SubagentWorkspaceContextEnricher()
    snippets = enricher.discover_context_snippets("/nonexistent/workspace/path")

    assert len(snippets) >= 3
    sources = {s.source_type for s in snippets}
    assert ContextSourceType.RULES in sources
    assert ContextSourceType.AGENTS_MD in sources
    assert ContextSourceType.README_MD in sources

    critical_snippets = [s for s in snippets if s.priority == RulePriority.CRITICAL]
    assert len(critical_snippets) >= 1
    assert "Security" in critical_snippets[0].title or "Destructive" in critical_snippets[0].content


def test_discover_snippets_from_physical_files(tmp_path: Path) -> None:
    """Verify parsing physical workspace context files along the priority chain."""
    # Create .rules
    rules_file = tmp_path / ".rules"
    rules_file.write_text(
        "# Absolute Security Redline\nNever run rm -rf ~/ or destructively delete database tables.\n\n"
        "# Type Hinting Standard\nStrict PEP 484 type annotations required. No Any allowed.\n",
        encoding="utf-8",
    )

    # Create AGENTS.md
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text(
        "# Architectural Responsibilities\nKeep modules decoupled with explicit interfaces.\n",
        encoding="utf-8",
    )

    enricher = SubagentWorkspaceContextEnricher()
    snippets = enricher.discover_context_snippets(str(tmp_path))

    assert len(snippets) >= 3
    sources = [s.source_type for s in snippets]
    assert sources[0] == ContextSourceType.RULES
    assert ContextSourceType.AGENTS_MD in sources

    # First section should be evaluated as CRITICAL due to 'redline'
    assert snippets[0].priority == RulePriority.CRITICAL


def test_rule_priority_determination() -> None:
    """Verify priority heuristic categorization for different rule contents."""
    enricher = SubagentWorkspaceContextEnricher()

    prio_crit = enricher._determine_priority("Security Redline", "No destructive drop table allowed")
    assert prio_crit == RulePriority.CRITICAL

    prio_high = enricher._determine_priority("Typing Standard", "All functions must specify type hints")
    assert prio_high == RulePriority.HIGH

    prio_norm = enricher._determine_priority("Workflow Guide", "Please use descriptive commit messages")
    assert prio_norm == RulePriority.NORMAL

    prio_low = enricher._determine_priority("About", "This is a demonstration project")
    assert prio_low == RulePriority.LOW


def test_prune_snippets_under_budget() -> None:
    """Verify that rules within budget are preserved in full without compacting."""
    config = WorkspaceInheritanceConfig(max_context_tokens=5000)
    enricher = SubagentWorkspaceContextEnricher(config)

    snippets = enricher.discover_context_snippets("/tmp/sample_workspace")
    pruned, is_compacted = enricher.prune_snippets_by_budget(snippets, config.max_context_tokens)

    assert not is_compacted
    assert len(pruned) == len(snippets)


def test_prune_snippets_over_budget_compacts_and_caps() -> None:
    """Verify differential compacting and budget capping when tokens exceed threshold."""
    # Set tight token budget (e.g. 20 tokens)
    config = WorkspaceInheritanceConfig(max_context_tokens=25, enable_compact_summarization=True)
    enricher = SubagentWorkspaceContextEnricher(config)

    snippets = enricher.discover_context_snippets("/tmp/sample_workspace")
    pruned, is_compacted = enricher.prune_snippets_by_budget(snippets, config.max_context_tokens)

    assert is_compacted
    total_tokens = sum(s.token_count for s in pruned)
    assert total_tokens <= config.max_context_tokens
    # Critical rule should be prioritized
    assert any(s.priority == RulePriority.CRITICAL for s in pruned)


def test_enrich_child_system_prompt_worker() -> None:
    """Verify prompt enrichment for a worker subagent embeddings."""
    enricher = SubagentWorkspaceContextEnricher()
    base_prompt = "You are a backend development assistant."

    result = enricher.enrich_child_system_prompt(
        base_prompt=base_prompt,
        workspace_root="/Users/dev/my-project",
        role=SubagentRole.WORKER,
    )

    assert result.original_prompt == base_prompt
    assert "Inherited Workspace Rules & Invariants" in result.enriched_prompt
    assert "/Users/dev/my-project" in result.enriched_prompt
    assert result.injected_token_count > 0
    assert len(result.matched_sources) >= 1
    assert len(enricher.get_audit_history()) == 1


def test_enrich_child_system_prompt_reviewer() -> None:
    """Verify prompt enrichment for a reviewer focuses on high/critical rules."""
    enricher = SubagentWorkspaceContextEnricher()
    base_prompt = "You are a QA reviewer."

    result = enricher.enrich_child_system_prompt(
        base_prompt=base_prompt,
        workspace_root="/Users/dev/my-project",
        role=SubagentRole.REVIEWER,
    )

    assert "CRITICAL" in result.enriched_prompt or "HIGH" in result.enriched_prompt
    for snippet in result.applied_snippets:
        assert snippet.priority in (RulePriority.CRITICAL, RulePriority.HIGH)


def test_audit_history_recording() -> None:
    """Verify audit record persistence and bounded storage."""
    enricher = SubagentWorkspaceContextEnricher()

    for i in range(5):
        enricher.enrich_child_system_prompt(
            base_prompt="Role prompt",
            workspace_root=f"/ws/path_{i}",
            role=SubagentRole.WORKER,
        )

    history = enricher.get_audit_history()
    assert len(history) == 5
    assert history[0].workspace_root == "/ws/path_0"
    assert history[4].workspace_root == "/ws/path_4"
