# [INPUT]: ActorVoiceMode, AdaptivePersonaPolicyEngine, AgentIdentitySpec, BootstrapLifecycleRunner, BootstrapRitualState, CanonicalAgentWorkspaceProtocolAndLifecycleSuite, CanonicalFileKind, CanonicalFileParser, DirectiveStatus, MultiTierWorkspaceMerger, RelationshipMaturityStage, RuntimeVibe, UserDirectiveItem
# [OUTPUT]: test_canonical_workspace_protocol_suite.py
# [POS]: tests/agent/workspace_rules/test_canonical_workspace_protocol_suite.py

"""Unit test suite for CanonicalAgentWorkspaceProtocolAndLifecycleSuite.

Verifies:
1. Canonical 5-file parser handling IDENTITY, USER (4000 char budget), and status tag annotations.
2. Multi-tier workspace merger preventing mutual exclusion between SOUL.md and AGENTS.md.
3. Adaptive persona policy engine evaluating maturity (Day 1 vs Day 40), runtime vibe, and real-talk fallback.
4. Bootstrap birth lifecycle runner detecting ritual and cleanly auto-pruning BOOTSTRAP.md.
5. End-to-end unified facade compiling full workspace injection and exporting dossier metadata.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.agent.workspace_rules.canonical_protocol import (
    ActorVoiceMode,
    AdaptivePersonaPolicyEngine,
    BootstrapLifecycleRunner,
    CanonicalAgentWorkspaceProtocolAndLifecycleSuite,
    CanonicalFileKind,
    CanonicalFileParser,
    DirectiveStatus,
    MultiTierWorkspaceMerger,
    RelationshipMaturityStage,
    RuntimeVibe,
)


def test_canonical_file_parser_identity_content() -> None:
    parser = CanonicalFileParser()

    identity_md = """# Agent Identity
- Name: Ada
- Creature: Cybernetic Falcon
- Vibe: Precision, calm, analytical
- Emoji: 🦅
- Avatar: assets/ada_avatar.png
"""
    spec = parser.parse_identity_content(identity_md)
    assert spec.name == "Ada"
    assert spec.creature == "Cybernetic Falcon"
    assert spec.vibe == "Precision, calm, analytical"
    assert spec.emoji == "🦅"
    assert spec.avatar_url == "assets/ada_avatar.png"


def test_canonical_file_parser_user_directives_budget_and_status() -> None:
    parser = CanonicalFileParser()

    user_md = """# User Preferences
<!-- observed: 2026-09-10 | status: active -->
- Prefer typed Python with strict type annotations
<!-- observed: 2026-09-12 | status: superseded -->
- Use tabs instead of spaces
- Always reply in Chinese
"""
    active, superseded = parser.parse_user_directives(user_md)
    assert len(active) == 2
    assert len(superseded) == 1
    assert "Prefer typed Python" in active[0].statement
    assert active[0].observed_date == "2026-09-10"
    assert active[0].status == DirectiveStatus.ACTIVE
    assert "Use tabs instead of spaces" in superseded[0].statement
    assert superseded[0].status == DirectiveStatus.SUPERSEDED
    assert "Always reply in Chinese" in active[1].statement

    # Test 4000 char budget containment
    oversized_text = "- Long instruction rule: " + ("x" * 5000)
    active_over, _ = parser.parse_user_directives(oversized_text)
    assert len(active_over) == 1
    assert len(active_over[0].statement) <= 4000


def test_multi_tier_workspace_merger_coexistence() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / CanonicalFileKind.SOUL.value).write_text(
            "Persona Core: Patient mentor.", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.IDENTITY.value).write_text(
            "- Name: MentorBot\n- Creature: Owl\n- Vibe: Calm\n- Emoji: 🦉", encoding="utf-8"
        )
        (workspace / "AGENTS.md").write_text(
            "Engineering Guardrails: Always run static analysis before push.", encoding="utf-8"
        )
        (workspace / "CLAUDE.md").write_text(
            "Assistant Instructions: Do not run rm -rf.", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.USER.value).write_text(
            "- Keep explanations succinct", encoding="utf-8"
        )

        merger = MultiTierWorkspaceMerger()
        merged = merger.merge_workspace(workspace)

        assert "MentorBot" in merged.system_persona_layer
        assert "Patient mentor" in merged.system_persona_layer
        assert "Always run static analysis" in merged.engineering_rules_layer
        assert "Do not run rm -rf" in merged.engineering_rules_layer
        assert "Keep explanations succinct" in merged.user_preferences_layer

        full_prompt = merged.render_full_system_prompt_block()
        assert "MentorBot" in full_prompt
        assert "Engineering Operating Rules" in full_prompt
        assert "Always run static analysis" in full_prompt
        assert "Active User Directives" in full_prompt


def test_adaptive_persona_policy_engine_maturity_and_vibe() -> None:
    engine = AdaptivePersonaPolicyEngine()

    # Day 1: onboarding guidance
    policy_day1 = engine.synthesize_policy(
        collaboration_days=1,
        user_query="Hello! Nice to meet you, who are you?",
    )
    assert policy_day1.stage == RelationshipMaturityStage.DAY_1_ONBOARDING
    assert policy_day1.voice_mode == ActorVoiceMode.IN_CHARACTER
    assert "DAY-1 ONBOARDING" in policy_day1.policy_instruction

    # Day 40: veteran zero-fluff
    policy_day40 = engine.synthesize_policy(
        collaboration_days=45,
        user_query="Run benchmark and show latency diff.",
    )
    assert policy_day40.stage == RelationshipMaturityStage.DAY_40_VETERAN_SYNERGY
    assert policy_day40.vibe == RuntimeVibe.CONCISE_COMMAND
    assert "DAY-40 VETERAN SYNERGY" in policy_day40.policy_instruction

    # Critical incident: Force Real-Talk transparent engineering override
    policy_incident = engine.synthesize_policy(
        collaboration_days=45,
        user_query="Warning: database corrupt, emergency stop immediately!",
        system_incident=True,
    )
    assert policy_incident.voice_mode == ActorVoiceMode.REAL_TALK
    assert policy_incident.vibe == RuntimeVibe.URGENT_INCIDENT
    assert "REAL-TALK ACTIVE" in policy_incident.policy_instruction


def test_bootstrap_lifecycle_runner_execution_and_pruning() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        bootstrap_file = workspace / CanonicalFileKind.BOOTSTRAP.value
        bootstrap_content = "1. Introduce yourself.\n2. Confirm architecture.\n3. Delete this file."
        bootstrap_file.write_text(bootstrap_content, encoding="utf-8")

        runner = BootstrapLifecycleRunner()
        initial_status = runner.check_bootstrap_status(workspace)
        assert initial_status.has_pending_bootstrap is True
        assert "First-Run Birth Sequence Ritual Active" in initial_status.ritual_instruction
        assert "Introduce yourself" in initial_status.ritual_instruction

        # Complete and prune BOOTSTRAP.md
        success = runner.complete_and_prune_bootstrap(workspace)
        assert success is True
        assert not bootstrap_file.exists()

        final_status = runner.check_bootstrap_status(workspace)
        assert final_status.has_pending_bootstrap is False
        assert final_status.ritual_instruction == ""


def test_canonical_suite_end_to_end_facade_and_dossier() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / CanonicalFileKind.SOUL.value).write_text(
            "Calculated and precise strategist.", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.IDENTITY.value).write_text(
            "- Name: Myrmidon\n- Creature: Sentinel\n- Vibe: Sharp\n- Emoji: 🛡️", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.USER.value).write_text(
            "- Use Python strict type hints", encoding="utf-8"
        )
        (workspace / "AGENTS.md").write_text(
            "- No unreviewed PR merges", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.TOOLS.value).write_text(
            "- Prefer ripgrep over grep", encoding="utf-8"
        )
        (workspace / CanonicalFileKind.BOOTSTRAP.value).write_text(
            "- Perform system check", encoding="utf-8"
        )

        suite = CanonicalAgentWorkspaceProtocolAndLifecycleSuite()

        bundle = suite.load_canonical_workspace(workspace)
        assert bundle.identity.name == "Myrmidon"
        assert bundle.identity.emoji == "🛡️"
        assert len(bundle.active_user_directives) == 1
        assert bundle.bootstrap_pending is True

        dossier = suite.export_dossier_deck_metadata(workspace)
        assert dossier["soul_configured"] is True
        assert dossier["active_directives_count"] == 1
        assert dossier["bootstrap_pending"] is True
        assert "Myrmidon" in str(dossier["identity"])

        # Compile full injection
        injection = suite.compile_full_workspace_injection(
            directory=workspace,
            collaboration_days=5,
            user_query="Status check",
        )
        assert "Myrmidon" in injection
        assert "Calculated and precise strategist" in injection
        assert "No unreviewed PR merges" in injection
        assert "Use Python strict type hints" in injection
        assert "Prefer ripgrep over grep" in injection
        assert "First-Run Birth Sequence Ritual Active" in injection
