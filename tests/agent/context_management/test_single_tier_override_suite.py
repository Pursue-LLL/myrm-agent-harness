"""Unit tests for SingleTierWorkspaceRuleOverrideInterceptorSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    OverrideResolutionKind,
    SingleTierRuleResolver,
    SingleTierWorkspaceRuleOverrideInterceptorSuite,
)


def test_single_tier_override_replaces_only_current_tier_and_preserves_root_baseline() -> None:
    """Test that AGENTS.override.md suppresses default AGENTS.md in current dir while inheriting root rules."""
    mock_files = {
        "/workspace/AGENTS.md": "GLOBAL BASELINE: Never expose credentials or .env files.",
        "/workspace/packages/backend/AGENTS.md": "BACKEND DEFAULT: Use legacy Flask setup.",
        "/workspace/packages/backend/AGENTS.override.md": "BACKEND OVERRIDE: Use modern FastAPI with strict Ruff lints.",
    }

    resolver = SingleTierRuleResolver(file_reader_mock=mock_files)
    suite = SingleTierWorkspaceRuleOverrideInterceptorSuite(resolver=resolver)

    receipt = suite.assemble_rules(
        target_dir="/workspace/packages/backend",
        workspace_root="/workspace",
    )

    assert receipt.resolution == OverrideResolutionKind.SINGLE_TIER_OVERRIDDEN
    assert len(receipt.effective_rule_chain) == 2

    # 1. Root rule preserved
    root_entry = receipt.effective_rule_chain[0]
    assert root_entry.file_path == "/workspace/AGENTS.md"
    assert root_entry.is_override is False
    assert "GLOBAL BASELINE" in root_entry.content

    # 2. Current tier override applied
    override_entry = receipt.effective_rule_chain[1]
    assert override_entry.file_path == "/workspace/packages/backend/AGENTS.override.md"
    assert override_entry.is_override is True
    assert "BACKEND OVERRIDE" in override_entry.content

    # 3. Default AGENTS.md in backend was suppressed
    assert "/workspace/packages/backend/AGENTS.md" in receipt.suppressed_default_files
    assert "Use legacy Flask setup" not in receipt.combined_prompt_content


def test_nested_child_not_polluted_by_ancestor_override() -> None:
    """Test that a nested child directory inherits the ancestor override while loading its own default rules."""
    mock_files = {
        "/workspace/AGENTS.md": "GLOBAL BASELINE: Security first.",
        "/workspace/packages/backend/AGENTS.override.md": "BACKEND OVERRIDE: Python 3.13 only.",
        "/workspace/packages/backend/services/billing/AGENTS.md": "BILLING RULES: Strict ledger reconciliation.",
    }

    resolver = SingleTierRuleResolver(file_reader_mock=mock_files)
    suite = SingleTierWorkspaceRuleOverrideInterceptorSuite(resolver=resolver)

    receipt = suite.assemble_rules(
        target_dir="/workspace/packages/backend/services/billing",
        workspace_root="/workspace",
    )

    assert len(receipt.effective_rule_chain) == 3
    assert receipt.effective_rule_chain[0].file_path == "/workspace/AGENTS.md"
    assert receipt.effective_rule_chain[1].file_path == "/workspace/packages/backend/AGENTS.override.md"
    assert receipt.effective_rule_chain[2].file_path == "/workspace/packages/backend/services/billing/AGENTS.md"
    assert receipt.effective_rule_chain[2].is_override is False

    # No suppression in billing directory
    assert "/workspace/packages/backend/services/billing/AGENTS.md" not in receipt.suppressed_default_files


def test_opt_out_flag_skips_all_context_files() -> None:
    """Test that opt_out_context_files=True (pi --no-context-files) skips reading any files."""
    mock_files = {
        "/workspace/AGENTS.md": "Should be ignored",
    }
    resolver = SingleTierRuleResolver(file_reader_mock=mock_files)
    suite = SingleTierWorkspaceRuleOverrideInterceptorSuite(resolver=resolver)

    receipt = suite.assemble_rules(
        target_dir="/workspace",
        workspace_root="/workspace",
        opt_out_context_files=True,
    )

    assert receipt.resolution == OverrideResolutionKind.OPT_OUT_DISABLED
    assert len(receipt.effective_rule_chain) == 0
    assert receipt.combined_prompt_content == ""


def test_cache_and_reload_and_explain_semantics() -> None:
    """Test caching, cache invalidation reload, and explanation diagnostics."""
    mock_files = {
        "/workspace/AGENTS.md": "Root rules v1",
        "/workspace/sub/AGENTS.override.md": "Override rules v1",
    }
    resolver = SingleTierRuleResolver(file_reader_mock=mock_files)
    suite = SingleTierWorkspaceRuleOverrideInterceptorSuite(resolver=resolver)

    # First fetch (cached)
    receipt1 = suite.assemble_rules("/workspace/sub", "/workspace", use_cache=True)
    assert receipt1.resolution == OverrideResolutionKind.SINGLE_TIER_OVERRIDDEN

    # Update virtual file
    mock_files["/workspace/sub/AGENTS.override.md"] = "Override rules v2 UPDATED"

    # Cached fetch returns old content
    receipt2 = suite.assemble_rules("/workspace/sub", "/workspace", use_cache=True)
    assert "v1" in receipt2.combined_prompt_content

    # Reload fetches updated content
    receipt_reloaded = suite.reload_rules("/workspace/sub", "/workspace")
    assert "v2 UPDATED" in receipt_reloaded.combined_prompt_content

    # Explain diagnostics
    explanation = suite.explain_override_effect("/workspace/sub", "/workspace")
    assert explanation["is_overridden"] is True
    assert explanation["active_overrides"] == ["/workspace/sub/AGENTS.override.md"]
    assert explanation["inherited_rules"] == ["/workspace/AGENTS.md"]
