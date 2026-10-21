"""Tests for Hermes / OpenViking lossless migration bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.domain_types import DomainCategory, MemoryDomain
from myrm_agent_harness.toolkits.memory.hermes_bridge import (
    import_hermes_bundle,
    parse_hermes_json,
    parse_hermes_markdown,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, SemanticMemory


def test_parse_hermes_markdown_with_frontmatter() -> None:
    doc = """---
id: hermes-pref-1
type: semantic
domain: user
category: preferences
summary_l0: Dark mode and high contrast preference
overview_l1: The user strongly prefers dark mode with high contrast accents.
---
# User UI Preferences

The user prefers high-contrast dark mode with neon green accents for terminal windows
and deep navy for coding editors. Never switch to light mode without asking.
"""
    memories = parse_hermes_markdown(doc)
    assert len(memories) == 1
    mem = memories[0]
    assert isinstance(mem, SemanticMemory)
    assert mem.id == "hermes-pref-1"
    assert mem.domain == MemoryDomain.USER
    assert mem.domain_category == DomainCategory.PREFERENCES.value
    assert mem.summary_l0 == "Dark mode and high contrast preference"
    assert mem.overview_l1 == "The user strongly prefers dark mode with high contrast accents."
    assert "neon green accents" in mem.content


def test_parse_hermes_markdown_heuristic_sections() -> None:
    doc = """# Agent Operational Guideline

## Overview
Always verify repository commit history before attempting destructive git resets.

## Details
1. Check `git status` and `git log -n 5`.
2. Ensure no uncommitted working tree changes exist.
3. If dirty, commit or request feedback before altering head pointer.
"""
    memories = parse_hermes_markdown(doc)
    assert len(memories) == 1
    mem = memories[0]
    assert mem.summary_l0.startswith("Agent Operational Guideline")
    assert "Always verify repository commit history" in mem.overview_l1
    assert mem.domain == MemoryDomain.TASK
    assert "Details" in mem.content


def test_parse_hermes_json() -> None:
    raw_json = """
    [
        {
            "id": "json-mem-1",
            "type": "procedural",
            "domain": "assistant",
            "domain_category": "soul",
            "summary_l0": "Maintain humble persona",
            "overview_l1": "Always respond politely and acknowledge limitations.",
            "trigger": "User expresses frustration",
            "action": "De-escalate calmly and apologize sincerely"
        }
    ]
    """
    memories = parse_hermes_json(raw_json)
    assert len(memories) == 1
    mem = memories[0]
    assert isinstance(mem, ProceduralMemory)
    assert mem.id == "json-mem-1"
    assert mem.domain == MemoryDomain.ASSISTANT
    assert mem.domain_category == DomainCategory.SOUL.value
    assert mem.trigger == "User expresses frustration"
    assert mem.action == "De-escalate calmly and apologize sincerely"


@pytest.mark.asyncio
async def test_import_hermes_bundle_mock() -> None:
    mock_manager = AsyncMock()
    mock_manager.save_memory = AsyncMock(return_value=None)

    bundle = """---
id: b-1
type: semantic
---
First memory content.
===
---
id: b-2
type: semantic
---
Second memory content.
"""
    success, failures = await import_hermes_bundle(mock_manager, bundle)
    assert success == 2
    assert failures == 0
    assert mock_manager.save_memory.call_count == 2
