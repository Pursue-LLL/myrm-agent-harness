"""Unit tests for Universal Agent Thin Harness adaptive contract and Token Tax governor.

Verifies ultra-thin system prompts for frontier models, persona fidelity preservation,
transient tool output dehydration GC, and transparent Token Tax audit snapshots.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.token_tax_governor import TokenTaxGovernor
from myrm_agent_harness.runtime.context.transient_tool_output_gc import (
    TransientToolOutputGCEngine,
)
from myrm_agent_harness.runtime.context.universal_thin_harness_types import (
    ModelCapabilityTier,
    OperatingDisciplineMode,
)
from myrm_agent_harness.runtime.context.universal_thin_prompt_generator import (
    UniversalThinPromptGenerator,
)


@pytest.fixture
def sample_multi_turn_messages() -> list[dict[str, str]]:
    """Generates a realistic 6-turn message history with historical and recent tool outputs."""
    long_diagnostic_log = (
        "DEBUG [2026-10-07 10:00:01] Worker thread 4 initialized.\n"
        "TRACE Checking configuration at /etc/app/config.yaml... FOUND\n"
        "INFO Loading 128 plugins into memory pool... OK\n"
        "WARN Slow response from database cluster replica 2: 120ms\n"
        "DEBUG Connection pool expanded from 10 to 25 slots.\n"
        "TRACE Resolving dependency graph across 84 services... OK\n"
        "INFO Ready to accept inbound RPC frames on port 9090.\n"
        "DEBUG Memory footprint stable at 245MB RSS.\n"
    ) * 3  # ~1,500 chars

    return [
        {"role": "user", "content": "Diagnose startup logs and identify why replica 2 was slow."},
        {"role": "assistant", "content": "Let me inspect the historical cluster logs."},
        {
            "role": "tool",
            "name": "read_logs",
            "id": "tool_001",
            "content": long_diagnostic_log,
        },
        {"role": "assistant", "content": "Replica 2 suffered a transient network hiccup. Now checking current status."},
        {
            "role": "tool",
            "name": "check_status",
            "id": "tool_002",
            "content": "HEALTH_OK: latency=12ms, replica_synced=true",
        },
        {"role": "assistant", "content": "Replica 2 has stabilized. All cluster nodes are green."},
    ]


def test_pure_mode_frontier_ultra_thin_prompt() -> None:
    """Pure mode with frontier model must produce ultra-thin skeleton (<200 tokens)."""
    generator = UniversalThinPromptGenerator()
    contract = generator.build_contract(
        mode=OperatingDisciplineMode.PURE,
        capability_tier=ModelCapabilityTier.FRONTIER,
        custom_persona="",
    )

    assert contract.mode == OperatingDisciplineMode.PURE
    assert contract.capability_tier == ModelCapabilityTier.FRONTIER
    assert contract.is_native_cot_passthrough is True
    # Overhead must be lean (<200 tokens)
    assert contract.estimated_overhead_tokens < 200
    assert "You are an autonomous AI companion" in contract.system_prompt_core


def test_persona_fidelity_and_primacy_in_pure_mode() -> None:
    """In Pure mode, custom persona must have primacy and not be diluted by system rules."""
    generator = UniversalThinPromptGenerator()
    custom_persona = (
        "You are Dr. Elena Vance, a distinguished astrophysicist specializing in orbital mechanics. "
        "Maintain an intellectually curious, rigorous, and dryly witty tone."
    )

    contract = generator.build_contract(
        mode=OperatingDisciplineMode.PURE,
        capability_tier=ModelCapabilityTier.FRONTIER,
        custom_persona=custom_persona,
    )

    assembled = generator.assemble_system_message(contract)

    # Custom persona must be placed at the very top of the system prompt
    assert assembled.startswith(custom_persona)
    assert "[Baseline Discipline]" in assembled
    assert contract.custom_persona_prompt == custom_persona


def test_lean_and_audit_modes_governance_contracts() -> None:
    """Lean mode enforces pragmatic engineering, while Audit mode enforces strict verification."""
    generator = UniversalThinPromptGenerator()

    lean_contract = generator.build_contract(
        mode=OperatingDisciplineMode.LEAN,
        capability_tier=ModelCapabilityTier.FRONTIER,
    )
    assert "minimum sufficient operations" in lean_contract.system_prompt_core

    audit_contract = generator.build_contract(
        mode=OperatingDisciplineMode.AUDIT,
        capability_tier=ModelCapabilityTier.STANDARD,
    )
    assert "Zero-trust verification" in audit_contract.system_prompt_core
    assert "Fail-closed" in audit_contract.system_prompt_core
    assert audit_contract.is_native_cot_passthrough is False


def test_transient_tool_output_gc_dehydration(sample_multi_turn_messages: list[dict[str, str]]) -> None:
    """Past verbose tool logs must be dehydrated while recent outputs remain untouched."""
    gc_engine = TransientToolOutputGCEngine(
        dehydration_char_threshold=200,
        keep_recent_turns=2,
    )

    cleaned, receipts = gc_engine.dehydrate_turn_history(sample_multi_turn_messages)

    assert len(cleaned) == len(sample_multi_turn_messages)
    assert len(receipts) == 1  # Only tool_001 is past threshold and outside recent window

    receipt = receipts[0]
    assert receipt.message_id == "tool_001"
    assert receipt.is_dehydrated is True
    assert receipt.saved_tokens > 200

    # Message 2 (tool_001) is dehydrated
    assert cleaned[2]["is_dehydrated"] == "true"
    assert "[Tool Output Dehydrated: tool=read_logs" in cleaned[2]["content"]

    # Message 4 (tool_002) is recent and was short anyway, remains verbatim
    assert "HEALTH_OK: latency=12ms" in cleaned[4]["content"]
    assert "is_dehydrated" not in cleaned[4]


def test_end_to_end_token_tax_governor(sample_multi_turn_messages: list[dict[str, str]]) -> None:
    """Governor coordinates thin prompt generation, GC, and yields comprehensive audit snapshot."""
    governor = TokenTaxGovernor()
    custom_persona = "You are a pragmatic systems architect."

    contract, cleaned_msgs, audit = governor.process_turn(
        mode=OperatingDisciplineMode.PURE,
        capability_tier=ModelCapabilityTier.FRONTIER,
        custom_persona=custom_persona,
        messages=sample_multi_turn_messages,
    )

    assert contract.mode == OperatingDisciplineMode.PURE
    assert audit.harness_overhead_tokens < 200
    assert audit.custom_persona_tokens > 0
    assert audit.cumulative_dehydrated_saved_tokens > 0
    assert audit.total_active_tokens > 0
    assert 0.0 <= audit.effective_tax_ratio <= 1.0

    # Ensure tool_001 was dehydrated in cleaned messages
    assert "[Tool Output Dehydrated:" in cleaned_msgs[2]["content"]
