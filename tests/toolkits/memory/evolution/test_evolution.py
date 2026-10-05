"""Unit tests for Order-Invariant Memory Evolution and Decay Engine."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.evolution import (
    ArbitrationAction,
    ConfidenceDecayGovernor,
    EvidenceContext,
    EvolvingMemoryRule,
    MemoryLineageSnapshotEngine,
    OrderInvarianceEvaluator,
    RuleStatus,
)


def _make_rule(
    rule_id: str,
    statement: str,
    contexts: list[EvidenceContext] | None = None,
    confidence: float = 0.85,
    half_life_days: float = 14.0,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_accessed_at: datetime | None = None,
    reinforcement_count: int = 0,
    status: RuleStatus = RuleStatus.CANDIDATE,
) -> EvolvingMemoryRule:
    """Helper to instantiate EvolvingMemoryRule with deterministic timestamps."""
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
    c_time = created_at or now
    u_time = updated_at or now
    a_time = last_accessed_at or now
    return EvolvingMemoryRule(
        rule_id=rule_id,
        statement=statement,
        domain="coding",
        evidence_contexts=contexts or [],
        confidence=confidence,
        half_life_days=half_life_days,
        created_at=c_time,
        updated_at=u_time,
        last_accessed_at=a_time,
        reinforcement_count=reinforcement_count,
        status=status,
    )


class TestOrderInvarianceEvaluator:
    """Test suite for out-of-order permutation resilience validation."""

    def test_robust_invariant_rule_passes_gate(self) -> None:
        """Symmetric, order-independent factual rules must pass out-of-order evaluation."""
        contexts = [
            EvidenceContext(
                context_id="ctx-1",
                description="Session 1 verification",
                facts=["Primary database is PostgreSQL 16", "ORM is SQLAlchemy 2.0"],
                temporal_index=0,
            ),
            EvidenceContext(
                context_id="ctx-2",
                description="Session 2 verification",
                facts=["Connection pool uses Asyncpg driver", "PostgreSQL 16 is enforced"],
                temporal_index=1,
            ),
        ]
        rule = _make_rule(
            rule_id="rule-pg-16",
            statement="Database backend is PostgreSQL 16 with asyncpg driver",
            contexts=contexts,
        )

        evaluator = OrderInvarianceEvaluator(invariance_threshold=0.90, max_permutations=4)
        promoted_rule, result = evaluator.evaluate_and_promote(rule)

        assert result.passed_gate is True
        assert result.invariance_score >= 0.90
        assert promoted_rule.status == RuleStatus.ACTIVE
        assert len(result.divergence_reasons) == 0

    def test_sequential_bias_rule_fails_gate(self) -> None:
        """Rules tied to transient sequential coupling must fail with penalties."""
        contexts = [
            EvidenceContext(
                context_id="ctx-1",
                description="Step 1",
                facts=["First step produced file X"],
                temporal_index=0,
            ),
            EvidenceContext(
                context_id="ctx-2",
                description="Step 2",
                facts=["Then subsequently read file X"],
                temporal_index=1,
            ),
        ]
        rule = _make_rule(
            rule_id="rule-bias-1",
            statement="First step must create file X, then subsequently read file X in the previous step",
            contexts=contexts,
        )

        evaluator = OrderInvarianceEvaluator(invariance_threshold=0.90)
        rejected_rule, result = evaluator.evaluate_and_promote(rule)

        assert result.passed_gate is False
        assert result.invariance_score < 0.90
        assert rejected_rule.status == RuleStatus.REJECTED
        assert len(result.divergence_reasons) > 0

    def test_zero_contexts_fails_gate(self) -> None:
        """Rule without evidence contexts immediately fails gate."""
        rule = _make_rule(rule_id="rule-empty", statement="Arbitrary unsupported claim", contexts=[])
        evaluator = OrderInvarianceEvaluator()
        result = evaluator.evaluate(rule)

        assert result.passed_gate is False
        assert result.invariance_score == 0.0


class TestConfidenceDecayGovernor:
    """Test suite for exponential half-life decay and conflict arbitration."""

    def test_half_life_decay_over_time(self) -> None:
        """Confidence decays by 50% after exactly one half-life period."""
        base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        rule = _make_rule(
            rule_id="rule-decay-1",
            statement="Service port is 8080",
            confidence=0.80,
            half_life_days=14.0,
            last_accessed_at=base_time,
        )

        governor = ConfidenceDecayGovernor(decay_cutoff_threshold=0.30)

        # Immediate check (delta = 0)
        conf_now = governor.compute_effective_confidence(rule, current_time=base_time)
        assert pytest.approx(conf_now, 0.01) == 0.80

        # After 14 days (1 half-life): 0.80 * 0.5 = 0.40
        time_14d = base_time + timedelta(days=14)
        conf_14d = governor.compute_effective_confidence(rule, current_time=time_14d)
        assert pytest.approx(conf_14d, 0.01) == 0.40
        assert rule.status == RuleStatus.CANDIDATE

        # After 28 days (2 half-lives): 0.80 * 0.25 = 0.20 < 0.30 cutoff -> DECAYED
        time_28d = base_time + timedelta(days=28)
        rule.status = RuleStatus.ACTIVE
        updated_rule = governor.evaluate_lifecycle(rule, current_time=time_28d)
        assert updated_rule.status == RuleStatus.DECAYED

    def test_reinforcement_boosts_confidence(self) -> None:
        """Reinforcement prevents premature decay by increasing effective confidence."""
        base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        rule = _make_rule(
            rule_id="rule-reinf",
            statement="Always run linters before commit",
            confidence=0.80,
            half_life_days=14.0,
            last_accessed_at=base_time,
            reinforcement_count=0,
            status=RuleStatus.ACTIVE,
        )

        governor = ConfidenceDecayGovernor()
        # Reinforce 3 times
        governor.reinforce(rule, reinforcement_time=base_time)
        governor.reinforce(rule, reinforcement_time=base_time)
        governor.reinforce(rule, reinforcement_time=base_time)

        assert rule.reinforcement_count == 3
        assert rule.confidence > 0.80

        # After 14 days, reinforced confidence should be strictly higher than unreinforced 0.40
        time_14d = base_time + timedelta(days=14)
        eff_conf = governor.compute_effective_confidence(rule, current_time=time_14d)
        assert eff_conf > 0.45

    def test_conflict_arbitration_replaces_decayed_with_new(self) -> None:
        """Decisive newer rule with higher confidence cleanly replaces decayed rule."""
        base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        old_rule = _make_rule(
            rule_id="old-branch",
            statement="Repository default branch is master",
            confidence=0.70,
            half_life_days=10.0,
            last_accessed_at=base_time,
            status=RuleStatus.ACTIVE,
        )

        # 30 days later, new rule asserts 'main'
        time_30d = base_time + timedelta(days=30)
        new_rule = _make_rule(
            rule_id="new-branch",
            statement="Repository default branch is main",
            confidence=0.90,
            created_at=time_30d,
            last_accessed_at=time_30d,
            status=RuleStatus.CANDIDATE,
        )

        governor = ConfidenceDecayGovernor()
        report = governor.arbitrate_conflict(old_rule, new_rule, current_time=time_30d)

        assert report.conflict_detected is True
        assert report.action == ArbitrationAction.REPLACE_WITH_NEW
        assert report.resolved_rule is not None
        assert report.resolved_rule.rule_id == "new-branch"
        assert old_rule.status == RuleStatus.REJECTED
        assert new_rule.status == RuleStatus.ACTIVE

    def test_conflict_arbitration_quarantines_ambiguous_tie(self) -> None:
        """Closely contested conflicting assertions without clear margin are quarantined."""
        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        rule_a = _make_rule(
            rule_id="auth-a",
            statement="Default auth mode is oauth2",
            confidence=0.85,
            last_accessed_at=now,
            status=RuleStatus.ACTIVE,
        )
        rule_b = _make_rule(
            rule_id="auth-b",
            statement="Default auth mode is api_key",
            confidence=0.86,
            last_accessed_at=now,
            status=RuleStatus.CANDIDATE,
        )

        governor = ConfidenceDecayGovernor(confidence_delta_margin=0.15)
        report = governor.arbitrate_conflict(rule_a, rule_b, current_time=now)

        assert report.conflict_detected is True
        assert report.action == ArbitrationAction.QUARANTINE_BOTH
        assert rule_a.status == RuleStatus.QUARANTINED
        assert rule_b.status == RuleStatus.QUARANTINED


class TestMemoryLineageSnapshotEngine:
    """Test suite for snapshot tree lineage, checksum integrity, and atomic rollback."""

    def test_snapshot_creation_and_integrity(self) -> None:
        """Snapshots must seal cryptographic digests and maintain parent links."""
        engine = MemoryLineageSnapshotEngine()
        rule1 = _make_rule("r1", "Config file is settings.toml", confidence=0.9)
        rule2 = _make_rule("r2", "Logging level is INFO", confidence=0.8)

        snap1 = engine.create_snapshot([rule1, rule2], commit_message="Initial baseline")
        assert snap1.parent_snapshot_id is None
        assert engine.verify_integrity(snap1.snapshot_id) is True

        rule3 = _make_rule("r3", "Timeout is 30 seconds", confidence=0.85)
        snap2 = engine.create_snapshot([rule1, rule2, rule3], commit_message="Add timeout config")
        assert snap2.parent_snapshot_id == snap1.snapshot_id
        assert engine.verify_integrity(snap2.snapshot_id) is True

        snaps = engine.list_snapshots()
        assert len(snaps) == 2
        assert snaps[0].snapshot_id == snap1.snapshot_id
        assert snaps[1].snapshot_id == snap2.snapshot_id

    def test_atomic_rollback(self) -> None:
        """Rollback restores historical rule state and creates a traceable rollback snapshot."""
        engine = MemoryLineageSnapshotEngine()
        rule1 = _make_rule("r1", "Config file is settings.toml", confidence=0.9)
        snap_initial = engine.create_snapshot([rule1], commit_message="Initial stable")

        # Mutate to corrupted state
        corrupted_rule = _make_rule("r1", "Corrupted invalid assertion", confidence=0.1)
        snap_bad = engine.create_snapshot([corrupted_rule], commit_message="Erroneous update")
        assert len(engine.list_snapshots()) == 2

        # Execute rollback to initial snapshot
        restored_rules, rollback_snap = engine.rollback(snap_initial.snapshot_id)

        assert len(restored_rules) == 1
        assert restored_rules[0].rule_id == "r1"
        assert restored_rules[0].statement == "Config file is settings.toml"
        assert restored_rules[0].confidence == 0.9

        # Audit trail must record the rollback as a 3rd snapshot
        assert len(engine.list_snapshots()) == 3
        assert rollback_snap.parent_snapshot_id == snap_bad.snapshot_id
        assert "Rollback to snapshot" in rollback_snap.commit_message
