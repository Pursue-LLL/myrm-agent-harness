"""Unit tests for CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite,
    CrossEcosystemRuleScanner,
    CrossEcosystemTranspiler,
    EcosystemSpecKind,
    RuleSectionCategory,
)


def test_multi_ecosystem_rule_discovery_across_tools() -> None:
    """Test scanner discovering rules across Claude, Cursor, Copilot, Windsurf, and Agentic AI."""
    mock_files = {
        "/workspace/CLAUDE.md": "# Claude Instructions\n## Build & Test\nRun `pnpm test`.\n## Code Style\nUse TypeScript.",
        "/workspace/.cursorrules": "# Cursor Rules\nAlways prefer functional programming.",
        "/workspace/.cursor/rules/fastapi.mdc": "# FastAPI Cursor Rule\nUse Pydantic v2 schemas.",
        "/workspace/.github/copilot-instructions.md": "# Copilot Prompt\nAdhere to PEP8 conventions.",
        "/workspace/.windsurfrules": "# Windsurf Rules\nKeep components under 200 lines.",
        "/workspace/AGENTS.md": "# Native Agents Spec\nLinux Foundation Agentic AI standard baseline.",
    }

    scanner = CrossEcosystemRuleScanner(mock_vfs=mock_files)
    suite = CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite(scanner=scanner)

    receipt = suite.inspect_and_transpile("/workspace")

    assert receipt.discovered_specs_count == 6
    found_ecosystems = {f.ecosystem for f in receipt.discovered_files}
    assert EcosystemSpecKind.CLAUDE_CODE in found_ecosystems
    assert EcosystemSpecKind.CURSOR_RULES in found_ecosystems
    assert EcosystemSpecKind.CURSOR_MDC in found_ecosystems
    assert EcosystemSpecKind.COPILOT_INSTRUCTIONS in found_ecosystems
    assert EcosystemSpecKind.WINDSURF_RULES in found_ecosystems
    assert EcosystemSpecKind.AGENTIC_AI_FOUNDATION in found_ecosystems


def test_cross_ecosystem_conflict_detection() -> None:
    """Test conflict detector flagging conflicting build/test tools between foreign files."""
    mock_files = {
        "/workspace/CLAUDE.md": "# Claude Rules\n## Build Commands\nUse `pnpm test` and `pnpm lint`.",
        "/workspace/.cursorrules": "# Cursor Rules\n## Test Commands\nExecute `npm test` and `yarn test`.",
    }

    scanner = CrossEcosystemRuleScanner(mock_vfs=mock_files)
    transpiler = CrossEcosystemTranspiler()
    suite = CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite(scanner=scanner, transpiler=transpiler)

    receipt = suite.inspect_and_transpile("/workspace")

    assert receipt.conflicts_count >= 1
    conflict = receipt.conflicts[0]
    assert conflict.category == RuleSectionCategory.BUILD_AND_TEST
    assert "pnpm" in conflict.conflict_description
    assert "npm" in conflict.conflict_description or "yarn" in conflict.conflict_description
    assert "Consolidate" in conflict.suggested_resolution


def test_transpilation_and_lossless_consolidation_to_standard_agents_md() -> None:
    """Test consolidating foreign rules into a standardized, lossless AGENTS.md document."""
    mock_files = {
        "/workspace/CLAUDE.md": "# Claude Guidelines\n## Overview\nMicroservices API gateway.\n## Security\nNever commit keys.",
        "/workspace/.cursorrules": "# Cursor Rules\n## Code Style\nEnforce strict typing in all modules.",
    }

    scanner = CrossEcosystemRuleScanner(mock_vfs=mock_files)
    suite = CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite(scanner=scanner)

    receipt = suite.inspect_and_transpile("/workspace")

    assert receipt.is_lossless is True
    assert "# AGENTS.md" in receipt.consolidated_agents_md
    assert "## Project Overview" in receipt.consolidated_agents_md
    assert "## Code Style & Engineering Standards" in receipt.consolidated_agents_md
    assert "## Security & Safety Guardrails" in receipt.consolidated_agents_md
    assert "## Imported Ecosystem Sources" in receipt.consolidated_agents_md

    # Check source text retention
    assert "Microservices API gateway" in receipt.consolidated_agents_md
    assert "Enforce strict typing in all modules" in receipt.consolidated_agents_md
    assert "Never commit keys" in receipt.consolidated_agents_md


def test_clean_workspace_without_foreign_rules() -> None:
    """Test graceful handling when no rule files are present in the workspace."""
    scanner = CrossEcosystemRuleScanner(mock_vfs={})
    suite = CrossEcosystemRuleMigrationAndCompatibilityInspectorSuite(scanner=scanner)

    receipt = suite.inspect_and_transpile("/empty_workspace")

    assert receipt.discovered_specs_count == 0
    assert receipt.conflicts_count == 0
    assert "No workspace rules defined" in receipt.consolidated_agents_md
