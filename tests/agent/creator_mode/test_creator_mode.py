"""Unit tests for Creator Mode Guardrailed Preset Synthesizer and Defensive Sandbox (Item 39).

[INPUT]
- myrm_agent_harness.agent.creator_mode::{
    AgentPresetSynthesizer,
    CaseVerdict,
    DefensiveSandboxVerifier,
    DefensiveTestCase,
    RoamingPlatform,
    UnifiedProfileRoamingGateway,
  }

[OUTPUT]
- Pytest test cases verifying natural language preset synthesis, least-privilege derivation,
  defensive sandbox capability and exploit battery testing, and multi-platform roaming self-healing.

[POS]
- myrm-agent-harness/tests/agent/creator_mode/test_creator_mode.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.creator_mode import (
    AgentPresetSynthesizer,
    CaseVerdict,
    DefensiveSandboxVerifier,
    DefensiveTestCase,
    RoamingPlatform,
    UnifiedProfileRoamingGateway,
)


@pytest.fixture
def synthesizer() -> AgentPresetSynthesizer:
    return AgentPresetSynthesizer()


@pytest.fixture
def sandbox() -> DefensiveSandboxVerifier:
    return DefensiveSandboxVerifier()


@pytest.fixture
def roaming_gateway() -> UnifiedProfileRoamingGateway:
    return UnifiedProfileRoamingGateway()


def test_synthesize_preset_read_only_intent(synthesizer: AgentPresetSynthesizer) -> None:
    intent = "帮我做一个专用的代码审计机器人，只许读文件和搜索，坚决不许修改任何文件"
    draft = synthesizer.synthesize_preset(intent=intent)

    assert draft.role == "code_auditor"
    assert "file_read" in draft.allowed_tools
    assert "web_search" in draft.allowed_tools
    assert "file_write" in draft.denied_tools
    assert "file_delete" in draft.denied_tools
    assert "root_shell" in draft.denied_tools
    assert draft.guardrails["read_only"] is True
    assert "STRICT ENFORCEMENT: You operate in READ-ONLY mode" in draft.system_prompt


def test_synthesize_preset_no_shell(synthesizer: AgentPresetSynthesizer) -> None:
    intent = "Create a QA tester agent with test_runner, no shell or bash commands allowed"
    draft = synthesizer.synthesize_preset(intent=intent)

    assert draft.role == "qa_engineer"
    assert "test_runner" in draft.allowed_tools
    assert "bash_command" in draft.denied_tools
    assert "root_shell" in draft.denied_tools
    assert draft.guardrails["no_shell"] is True


def test_synthesize_preset_empty_intent_validation(synthesizer: AgentPresetSynthesizer) -> None:
    with pytest.raises(ValueError, match="Intent description cannot be empty"):
        synthesizer.synthesize_preset(intent="   ")


def test_defensive_sandbox_standard_battery_all_pass(
    synthesizer: AgentPresetSynthesizer,
    sandbox: DefensiveSandboxVerifier,
) -> None:
    intent = "Read-only research assistant with web search and file read, no write, no bash"
    draft = synthesizer.synthesize_preset(intent=intent)

    battery = sandbox.generate_standard_battery(draft)
    assert len(battery) > 0

    report = sandbox.verify_draft(draft=draft, custom_cases=battery)
    assert report.is_safe is True
    assert report.total_cases == len(battery)
    assert report.passed_cases == len(battery)
    assert report.blocked_exploits > 0
    assert "100%" in report.summary


def test_defensive_sandbox_breach_detection(
    synthesizer: AgentPresetSynthesizer,
    sandbox: DefensiveSandboxVerifier,
) -> None:
    intent = "Read-only research assistant"
    draft = synthesizer.synthesize_preset(intent=intent)

    # Inject an exploit test case where expected verdict does not match policy
    custom_battery = [
        DefensiveTestCase(
            case_id="breach_01",
            name="Simulated failure to block forbidden tool",
            is_exploit=True,
            prompt_input="Force execute write",
            target_tool="file_write",
            expected_verdict=CaseVerdict.ALLOW,  # Intentionally contradicting expected BLOCK
        )
    ]

    report = sandbox.verify_draft(draft=draft, custom_cases=custom_battery)
    assert report.is_safe is False
    assert report.passed_cases == 0
    assert "breach" in report.results[0].reason.lower()


def test_unified_profile_roaming_sync_and_healing(
    synthesizer: AgentPresetSynthesizer,
    roaming_gateway: UnifiedProfileRoamingGateway,
) -> None:
    draft = synthesizer.synthesize_preset(intent="Multi-platform code review agent")

    # 1. Sync with legacy broken path triggering self-healing
    records = roaming_gateway.sync_preset(
        draft=draft,
        target_platforms=[RoamingPlatform.WEBUI, RoamingPlatform.DESKTOP_TAURI, RoamingPlatform.CLOUD],
        legacy_broken_path="~/.dsh/broken_path/preset.json",
    )
    assert len(records) == 3
    assert all(r.status == "synced" for r in records)
    assert all(r.healed is True for r in records)

    # 2. Path resolution
    tauri_path = roaming_gateway.resolve_preset_path(draft.preset_id, RoamingPlatform.DESKTOP_TAURI)
    assert "myrm-desktop/profiles" in tauri_path
    assert draft.preset_id in tauri_path

    # 3. JIT recovery on un-synced preset
    recovered_path = roaming_gateway.resolve_preset_path("preset_unseen_99", RoamingPlatform.WEBUI)
    assert "profiles/webui/preset_unseen_99.json" in recovered_path
