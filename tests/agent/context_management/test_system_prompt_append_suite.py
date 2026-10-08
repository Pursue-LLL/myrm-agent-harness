"""Unit tests for SystemPromptStrongAppendChannelSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    PromptChannelKind,
    SystemPromptAppendLoader,
    SystemPromptStrongAppendChannelSuite,
)


def test_system_prompt_strong_append_combines_global_and_workspace_directives() -> None:
    """Test that global and workspace append-system.md files are safely appended to base system prompt."""
    mock_files = {
        "~/.myrm/agent/append-system.md": "GLOBAL MANDATE: Always redact API credentials.",
        "/workspace/.myrm/append-system.md": "WORKSPACE MANDATE: Follow Python 3.13 strict type annotations.",
    }
    loader = SystemPromptAppendLoader(mock_vfs=mock_files)
    suite = SystemPromptStrongAppendChannelSuite(loader=loader)

    base_prompt = "You are Myrm Agent, a high-performance cognitive assistant."
    receipt = suite.assemble_system_prompt(
        base_system_prompt=base_prompt,
        workspace_root="/workspace",
        allow_full_replace=False,
    )

    assert receipt.is_replaced is False
    assert PromptChannelKind.BASE_CORE_SYSTEM in receipt.injected_channels
    assert PromptChannelKind.STRONG_APPEND_SYSTEM in receipt.injected_channels

    # Base prompt must be at the very top
    assert receipt.final_system_prompt.startswith(base_prompt)

    # Must contain strong append fence
    assert "<<<SYSTEM_APPEND_STRONG_DIRECTIVES>>>" in receipt.final_system_prompt
    assert "<<<END_SYSTEM_APPEND_STRONG_DIRECTIVES>>>" in receipt.final_system_prompt

    # Verify both directives are injected in priority order (global first, workspace next)
    assert "GLOBAL MANDATE" in receipt.final_system_prompt
    assert "WORKSPACE MANDATE" in receipt.final_system_prompt
    idx_global = receipt.final_system_prompt.find("GLOBAL MANDATE")
    idx_workspace = receipt.final_system_prompt.find("WORKSPACE MANDATE")
    assert idx_global < idx_workspace


def test_full_replace_system_channel_requires_explicit_authorization() -> None:
    """Test that SYSTEM.md is only applied when allow_full_replace is explicitly set to True."""
    mock_files = {
        "/workspace/SYSTEM.md": "COMPLETELY REPLACED CUSTOM SYSTEM PROMPT.",
    }
    loader = SystemPromptAppendLoader(mock_vfs=mock_files)
    suite = SystemPromptStrongAppendChannelSuite(loader=loader)
    base_prompt = "Base Agent Prompt"

    # 1. Without authorization, SYSTEM.md is ignored
    receipt_ignored = suite.assemble_system_prompt(
        base_system_prompt=base_prompt,
        workspace_root="/workspace",
        allow_full_replace=False,
    )
    assert receipt_ignored.is_replaced is False
    assert receipt_ignored.final_system_prompt == base_prompt

    # 2. With authorization, SYSTEM.md completely replaces base prompt
    receipt_replaced = suite.assemble_system_prompt(
        base_system_prompt=base_prompt,
        workspace_root="/workspace",
        allow_full_replace=True,
    )
    assert receipt_replaced.is_replaced is True
    assert receipt_replaced.final_system_prompt == "COMPLETELY REPLACED CUSTOM SYSTEM PROMPT."
    assert receipt_replaced.injected_channels == [PromptChannelKind.FULL_REPLACE_SYSTEM]


def test_anti_drift_compliance_verification() -> None:
    """Test mandatory keywords verification for enterprise anti-drift governance."""
    mock_files = {
        "/workspace/append-system.md": "COMPLIANCE: [NO_SECRET_LEAK] enforced.",
    }
    loader = SystemPromptAppendLoader(mock_vfs=mock_files)
    suite = SystemPromptStrongAppendChannelSuite(loader=loader)

    # Test passing compliance
    receipt_pass = suite.assemble_system_prompt(
        base_system_prompt="Base prompt",
        workspace_root="/workspace",
        mandatory_anti_drift_keywords=["[NO_SECRET_LEAK]"],
    )
    assert receipt_pass.anti_drift_verified is True

    # Test failing compliance when keyword is absent
    receipt_fail = suite.assemble_system_prompt(
        base_system_prompt="Base prompt",
        workspace_root="/workspace",
        mandatory_anti_drift_keywords=["[GDPR_AUDIT_REQUIRED]"],
    )
    assert receipt_fail.anti_drift_verified is False


def test_empty_append_fallthrough_to_base_prompt() -> None:
    """Test clean passthrough when no append files exist in workspace or home."""
    loader = SystemPromptAppendLoader(mock_vfs={})
    suite = SystemPromptStrongAppendChannelSuite(loader=loader)

    base = "Clean Base System Prompt."
    receipt = suite.assemble_system_prompt(base, workspace_root="/workspace")

    assert receipt.final_system_prompt == base
    assert receipt.is_replaced is False
    assert len(receipt.active_sources) == 0
    assert "<<<SYSTEM_APPEND_STRONG_DIRECTIVES>>>" not in receipt.final_system_prompt
