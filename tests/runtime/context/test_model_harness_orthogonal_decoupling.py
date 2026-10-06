"""Tests for Model-Harness orthogonal decoupling, multi-gateway trust, and scoped rules handoff.

Covers:
1. Total Cost-to-Outcome (TCO) routing
2. Gateway trust tiering, high-risk interception, and signed Handoff Cards
3. Five-layer rule topology precedence arbitration and anti-bloat GC
4. Tri-state context pruning and physical Reality Cross-Check
5. Subagent parallel worktree isolation and merge reconciliation
6. Hermes/OpenClaw rules asset importing
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.context.five_layer_rule_arbiter import (
    FiveLayerRuleArbiter,
)
from myrm_agent_harness.runtime.context.model_harness_cost_router import (
    ModelHarnessCostRouter,
)
from myrm_agent_harness.runtime.context.multi_gateway_trust_governor import (
    MultiGatewayTrustGovernor,
)
from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    FiveLayerRuleMatrix,
    GatewayTrustTier,
    HandoffCardStatus,
    HighRiskActionKind,
    ModelCostProfile,
    PrunedContextItem,
    RuleEntry,
    RuleLayerKind,
    TaskComplexity,
    TriStateTag,
)
from myrm_agent_harness.runtime.context.scoped_rules_importer import (
    ScopedRulesImporter,
)
from myrm_agent_harness.runtime.context.subagent_worktree_isolator import (
    SubagentWorktreeIsolator,
)
from myrm_agent_harness.runtime.context.tri_state_handoff_engine import (
    TriStateHandoffEngine,
)


def test_model_harness_cost_router_tco_selection() -> None:
    """Validate that cost-to-outcome router accounts for retry penalty rather than token price alone."""
    cheap_fragile = ModelCostProfile(
        model_id="cheap-small-model",
        input_token_rate_per_k=0.001,
        output_token_rate_per_k=0.002,
        historical_success_rate=0.40,
        avg_latency_ms=250.0,
        complexity_success_rates={
            TaskComplexity.SIMPLE_LOOKUP: 0.95,
            TaskComplexity.COMPLEX_REFACTOR: 0.25,
        },
    )
    strong_reliable = ModelCostProfile(
        model_id="strong-flagship-model",
        input_token_rate_per_k=0.005,
        output_token_rate_per_k=0.015,
        historical_success_rate=0.95,
        avg_latency_ms=800.0,
        complexity_success_rates={
            TaskComplexity.SIMPLE_LOOKUP: 0.98,
            TaskComplexity.COMPLEX_REFACTOR: 0.95,
        },
    )

    router = ModelHarnessCostRouter(
        candidate_models=[cheap_fragile, strong_reliable],
        retry_penalty_multiplier=2.0,
    )

    # For a complex refactoring task, fragile model retry penalties push its expected TCO higher
    decision_complex = router.route_task(
        complexity=TaskComplexity.COMPLEX_REFACTOR,
        estimated_input_k_tokens=10.0,
        estimated_output_k_tokens=3.0,
    )
    assert decision_complex.selected_model == "strong-flagship-model"
    assert "Harness governs" in decision_complex.harness_responsibility

    # For simple lookup, cheap model succeeds reliably and wins on pure cost
    decision_simple = router.route_task(
        complexity=TaskComplexity.SIMPLE_LOOKUP,
        estimated_input_k_tokens=1.0,
        estimated_output_k_tokens=0.2,
    )
    assert decision_simple.selected_model == "cheap-small-model"


def test_multi_gateway_trust_interception_and_signed_handoff() -> None:
    """Validate high-risk action interception on mobile and approval on desktop."""
    secret = "test-hmac-secure-secret-key-42"
    governor = MultiGatewayTrustGovernor(hmac_secret_key=secret)

    # CLI / Desktop have direct clearance
    assert governor.is_action_permitted(
        GatewayTrustTier.CLI_TRUSTED, HighRiskActionKind.FILE_DELETION
    )
    assert governor.is_action_permitted(
        GatewayTrustTier.DESKTOP_TRUSTED, HighRiskActionKind.PROD_DEPLOYMENT
    )

    # Mobile is restricted from file deletion and secret access
    assert not governor.is_action_permitted(
        GatewayTrustTier.MOBILE_RESTRICTED, HighRiskActionKind.FILE_DELETION
    )

    # Attempt file deletion from mobile -> produces signed handoff card
    card = governor.intercept_and_create_handoff(
        source_gateway=GatewayTrustTier.MOBILE_RESTRICTED,
        action_kind=HighRiskActionKind.FILE_DELETION,
        action_payload="rm -rf /workspace/build",
        session_id="session-xyz-101",
        explanation="User requested build cleanup via mobile chat.",
    )

    assert card.status == HandoffCardStatus.PENDING_APPROVAL
    assert len(card.signature) == 64  # sha256 hex string

    # Attempting to approve from another mobile gateway must fail
    success_mobile, msg_mobile, _ = governor.verify_and_approve_handoff(
        handoff_id=card.handoff_id,
        current_gateway=GatewayTrustTier.MOBILE_RESTRICTED,
    )
    assert not success_mobile
    assert "lacks permissions" in msg_mobile

    # Approving from trusted Desktop succeeds and mutates status
    success_desktop, _msg_desktop, approved_card = governor.verify_and_approve_handoff(
        handoff_id=card.handoff_id,
        current_gateway=GatewayTrustTier.DESKTOP_TRUSTED,
    )
    assert success_desktop
    assert approved_card is not None
    assert approved_card.status == HandoffCardStatus.APPROVED_EXECUTED


def test_five_layer_rule_precedence_and_gc() -> None:
    """Verify Corrections > VOICE > CONTEXT > AGENTS > SOUL arbitration and GC."""
    arbiter = FiveLayerRuleArbiter()

    # Conflicting rules on code styling in different layers
    soul_rule = RuleEntry(
        rule_id="soul_style",
        layer=RuleLayerKind.SOUL,
        category="code_formatting",
        content="Prefer tabs for indentation.",
    )
    agents_rule = RuleEntry(
        rule_id="agents_style",
        layer=RuleLayerKind.AGENTS,
        category="code_formatting",
        content="Use 2 spaces for all python indentation.",
    )
    corrections_rule = RuleEntry(
        rule_id="corrections_style",
        layer=RuleLayerKind.CORRECTIONS,
        category="code_formatting",
        content="Mandatory 4 spaces PEP8 indentation; never use tabs or 2 spaces.",
    )
    ephemeral_rule = RuleEntry(
        rule_id="temp_rule",
        layer=RuleLayerKind.CONTEXT,
        category="temporary_debug",
        content="仅限本次：print every single AST node.",
        is_ephemeral=True,
    )

    matrix = FiveLayerRuleMatrix(
        soul_rules=(soul_rule,),
        agents_rules=(agents_rule,),
        context_rules=(ephemeral_rule,),
        corrections_rules=(corrections_rule,),
    )

    surviving, resolutions = arbiter.resolve_conflicts_and_assemble(matrix)

    # CORRECTIONS has highest priority score (100) and must win the code_formatting category
    formatting_winner = next(r for r in surviving if r.category == "code_formatting")
    assert formatting_winner.layer == RuleLayerKind.CORRECTIONS
    assert "Mandatory 4 spaces" in formatting_winner.content

    assert len(resolutions) == 1
    assert resolutions[0].winning_rule.rule_id == "corrections_style"
    assert len(resolutions[0].suppressed_rules) == 2

    # Test Garbage Collection: ephemeral rule must be pruned
    retained, pruned = arbiter.garbage_collect_rules(surviving, drop_ephemeral=True)
    assert any(p.rule_id == "temp_rule" for p in pruned)
    assert all(r.rule_id != "temp_rule" for r in retained)

    # Test markdown formatting
    md_output = arbiter.render_markdown_context(retained)
    assert "Active Operational Rules" in md_output
    assert "Layer: CORRECTIONS" in md_output


def test_tri_state_handoff_and_reality_cross_check() -> None:
    """Test tri-state context separation and reality check verification against filesystem."""
    engine = TriStateHandoffEngine()

    items = (
        PrunedContextItem(
            item_id="1",
            tag=TriStateTag.KEEP,
            source_type="decision",
            original_content="Selected SQLite over Postgres for single-sandbox deployment.",
            processed_content="Selected SQLite over Postgres.",
        ),
        PrunedContextItem(
            item_id="2",
            tag=TriStateTag.COMPRESS,
            source_type="tool_output",
            original_content="Ran 500 lines of pytest verbose log output...",
            processed_content="Pytest 8/8 passed in 2.1s.",
        ),
        PrunedContextItem(
            item_id="3",
            tag=TriStateTag.DISCARD,
            source_type="thought",
            original_content="Maybe we could use Redis? Wait, no, too heavy.",
            processed_content="",
        ),
    )

    kept, compressed, discarded = engine.classify_and_prune(items)
    assert len(kept) == 1
    assert len(compressed) == 1
    assert len(discarded) == 1

    manifest = engine.assemble_handoff_manifest(
        task_goal="Migrate context persistence",
        kept_items=kept,
        compressed_items=compressed,
        declared_files=("src/app.py", "missing_file.py"),
    )
    assert "Structured Task Handoff Manifest" in manifest

    # Reality Cross-Check test in a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "app.py").write_text("print('hello')", encoding="utf-8")

        receipt = engine.cross_check_reality(
            workspace_root=str(tmp_path),
            declared_files=("src/app.py", "missing_file.py"),
        )

        assert not receipt.verified
        assert "missing_file.py" in receipt.missing_files
        assert len(receipt.discrepancies) == 1


def test_subagent_worktree_isolation_and_reconciliation() -> None:
    """Test Subagent workspace path isolation and merge collision detection."""
    isolator = SubagentWorktreeIsolator(base_worktree_dir="/tmp/test_worktrees")

    alloc_a = isolator.allocate_worktree("subagent_1", "frontend_auth")
    alloc_b = isolator.allocate_worktree("subagent_2", "backend_api")

    assert alloc_a.isolated_path != alloc_b.isolated_path

    # Subagent 1 modifies auth.ts and user.ts
    isolator.record_file_modification("subagent_1", "src/auth.ts")
    isolator.record_file_modification("subagent_1", "src/user.ts")

    # Subagent 2 modifies server.py and user.ts (conflict on user.ts!)
    isolator.record_file_modification("subagent_2", "src/server.py")
    isolator.record_file_modification("subagent_2", "src/user.ts")

    result = isolator.reconcile_and_merge(["subagent_1", "subagent_2"])
    assert result.has_conflict
    assert any("src/user.ts" in c for c in result.conflicting_files)
    assert len(result.merged_files) == 3


def test_scoped_rules_importer_from_hermes_markdown() -> None:
    """Test importing Hermes markdown files into FiveLayerRuleMatrix."""
    importer = ScopedRulesImporter()

    file_bundle = {
        "SOUL.md": "# Worldview\n- Always act in user's best interest\n- [Bedrock] Be truthful",
        "AGENTS.md": "- [Architecture] Maintain <400 lines per file\n- Never use Any",
        "CONTEXT.md": "- [Project] open-perplexity sandbox harness",
        "VOICE.md": "- [Style] Professional and concise technical tone",
        "Corrections.md": "- [PEP8] Always use 4 spaces indentation",
    }

    matrix = importer.import_from_file_bundle(file_bundle)

    assert len(matrix.soul_rules) == 2
    assert len(matrix.agents_rules) == 2
    assert len(matrix.context_rules) == 1
    assert len(matrix.voice_rules) == 1
    assert len(matrix.corrections_rules) == 1

    # Check category extraction
    agents_cat = matrix.agents_rules[0].category
    assert agents_cat == "Architecture"
    assert matrix.corrections_rules[0].category == "PEP8"
