"""Unit tests for Temporal Validity and Fact Expiration Governance Engine."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.temporal import (
    FactExpirationArchiver,
    FactTemporalState,
    TemporalFactRecord,
    TemporalValidityGovernor,
)


def _make_fact(
    fact_id: str,
    subject: str = "frontend_app",
    predicate: str = "framework",
    value: str = "React 18",
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    confidence: float = 0.90,
    status: FactTemporalState = FactTemporalState.ACTIVE,
) -> TemporalFactRecord:
    """Helper to instantiate TemporalFactRecord with deterministic parameters."""
    t_from = valid_from or datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return TemporalFactRecord(
        fact_id=fact_id,
        subject=subject,
        predicate=predicate,
        value=value,
        valid_from=t_from,
        valid_to=valid_to,
        confidence=confidence,
        status=status,
    )


class TestTemporalValidityGovernor:
    """Test suite for interval checking, temporal decay, and conflict suppression."""

    def test_temporal_validity_interval_checks(self) -> None:
        """Records must evaluate valid only within their [valid_from, valid_to] lifespan."""
        governor = TemporalValidityGovernor()
        t_start = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
        t_end = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

        fact = _make_fact("fact-bounded", valid_from=t_start, valid_to=t_end)

        # Before valid_from -> invalid
        assert governor.is_valid_at(fact, query_time=t_start - timedelta(days=1)) is False

        # Exactly at valid_from -> valid
        assert governor.is_valid_at(fact, query_time=t_start) is True

        # In mid-interval -> valid
        assert governor.is_valid_at(fact, query_time=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)) is True

        # After valid_to -> invalid
        assert governor.is_valid_at(fact, query_time=t_end + timedelta(days=1)) is False

    def test_open_ended_fact_remains_valid(self) -> None:
        """Facts without valid_to bound remain active indefinitely after valid_from."""
        governor = TemporalValidityGovernor()
        t_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        fact = _make_fact("fact-open", valid_from=t_start, valid_to=None)

        far_future = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert governor.is_valid_at(fact, query_time=far_future) is True

    def test_temporal_decay_computation(self) -> None:
        """Decay score should halve after exactly one half-life period."""
        governor = TemporalValidityGovernor()
        base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        fact = _make_fact("fact-decay", valid_from=base_time, confidence=0.80)

        # Decay after 30 days (1 half-life of 30 days): 0.80 * 0.5 = 0.40
        time_30d = base_time + timedelta(days=30)
        decayed_conf = governor.compute_temporal_decay(fact, current_time=time_30d, half_life_days=30.0)
        assert pytest.approx(decayed_conf, 0.01) == 0.40

    def test_conflict_suppression_supersedes_obsolete_facts(self) -> None:
        """Newer factual assertion on same (subject, predicate) supersedes older historical fact."""
        governor = TemporalValidityGovernor(suppression_penalty_ratio=0.90)

        old_fact = _make_fact(
            "fact-old",
            subject="frontend_stack",
            predicate="framework",
            value="React 18",
            valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            confidence=0.85,
        )
        new_fact = _make_fact(
            "fact-new",
            subject="frontend_stack",
            predicate="framework",
            value="Vue 3",
            valid_from=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
            confidence=0.95,
        )

        governed, reports = governor.suppress_conflicting_facts([old_fact, new_fact])

        assert len(reports) == 1
        report = reports[0]
        assert report.conflict_detected is True
        assert report.prevailing_fact_id == "fact-new"
        assert "fact-old" in report.suppressed_fact_ids

        # Verify fact states in governed output
        fact_dict = {f.fact_id: f for f in governed}
        assert fact_dict["fact-new"].status == FactTemporalState.ACTIVE
        assert fact_dict["fact-old"].status == FactTemporalState.SUPERSEDED
        assert fact_dict["fact-old"].superseded_by_id == "fact-new"
        # Old fact confidence should be heavily penalized
        assert fact_dict["fact-old"].confidence < 0.15

    def test_identical_values_no_conflict_suppression(self) -> None:
        """Multiple facts affirming the same value produce zero collision reports."""
        governor = TemporalValidityGovernor()
        fact1 = _make_fact("f1", subject="db", predicate="engine", value="PostgreSQL 16")
        fact2 = _make_fact("f2", subject="db", predicate="engine", value="postgresql 16")

        governed, reports = governor.suppress_conflicting_facts([fact1, fact2])
        assert len(reports) == 0
        assert len(governed) == 2


class TestFactExpirationArchiver:
    """Test suite for pruning expired facts into cold storage."""

    def test_scan_and_archive_expired_facts(self) -> None:
        """Archiver separates active vs expired facts and stores expired facts in cold archive."""
        archiver = FactExpirationArchiver()
        now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

        fact_valid = _make_fact(
            "f-valid",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 12, 1, tzinfo=UTC),
        )
        fact_expired = _make_fact(
            "f-expired",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 5, 1, tzinfo=UTC),  # expired prior to June
        )

        retained, result = archiver.scan_and_archive([fact_valid, fact_expired], current_time=now)

        assert len(retained) == 1
        assert retained[0].fact_id == "f-valid"
        assert result.expired_count == 1
        assert result.archived_count == 1
        assert "f-expired" in result.archived_fact_ids

        # Check cold storage retrieval
        assert archiver.archive_size == 1
        cold_record = archiver.get_archived_fact("f-expired")
        assert cold_record is not None
        assert cold_record.status == FactTemporalState.ARCHIVED

    def test_restore_archived_fact(self) -> None:
        """Restoring a cold archived fact returns it to ACTIVE status and clears from archive."""
        archiver = FactExpirationArchiver()
        now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        fact_expired = _make_fact(
            "f-revived",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 5, 1, tzinfo=UTC),
        )

        archiver.scan_and_archive([fact_expired], current_time=now)
        assert archiver.archive_size == 1

        restored = archiver.restore_fact("f-revived")
        assert restored is not None
        assert restored.status == FactTemporalState.ACTIVE
        assert archiver.archive_size == 0
