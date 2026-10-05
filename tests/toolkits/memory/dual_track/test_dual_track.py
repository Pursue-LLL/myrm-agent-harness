"""Unit tests for Dual-Track Fact Decision and Verbatim Evidence Tracer Engine."""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.dual_track import (
    DualTrackDecisionTracer,
    VerbatimEvidenceSlice,
)


def _make_evidence(
    evidence_id: str,
    snippet: str,
    speaker: str = "user",
    timestamp: datetime | None = None,
) -> VerbatimEvidenceSlice:
    """Helper to instantiate VerbatimEvidenceSlice."""
    ts = timestamp or datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    return VerbatimEvidenceSlice(
        evidence_id=evidence_id,
        session_id="sess-dual-01",
        turn_id="turn-01",
        speaker=speaker,
        snippet=snippet,
        timestamp=ts,
    )


class TestDualTrackDecisionTracer:
    """Test suite for dual-track separation between state facts and verbatim evidence."""

    def test_set_and_get_fact_basic(self) -> None:
        """Tracer must store and retrieve structured facts by key and by fact_id."""
        tracer = DualTrackDecisionTracer()
        entry = tracer.set_fact(
            key="runtime.python_version",
            value="3.13.1",
            confidence=0.99,
            scope="workspace",
        )

        assert entry.key == "runtime.python_version"
        assert entry.value == "3.13.1"
        assert entry.confidence == 0.99
        assert tracer.total_facts == 1

        # Retrieve by key
        retrieved = tracer.get_fact("runtime.python_version")
        assert retrieved is not None
        assert retrieved.fact_id == entry.fact_id

        # Retrieve by fact_id
        retrieved_by_id = tracer.get_fact(entry.fact_id)
        assert retrieved_by_id is not None
        assert retrieved_by_id.key == "runtime.python_version"

    def test_evidence_registration_and_pointer_binding(self) -> None:
        """Facts must bind bidirectional pointers to registered verbatim evidence slices."""
        tracer = DualTrackDecisionTracer()
        ev1 = _make_evidence("ev-101", "User said: Please set PostgreSQL port to 5432.")
        ev2 = _make_evidence("ev-102", "Assistant confirmed: Port 5432 is verified.")

        tracer.register_evidence(ev1)
        tracer.register_evidence(ev2)
        assert tracer.total_evidence_slices == 2

        fact = tracer.set_fact(
            key="database.port",
            value="5432",
            evidence_ids=["ev-101"],
        )
        assert fact.evidence_ref_ids == ["ev-101"]

        # Update fact with additional evidence pointer without duplication
        updated_fact = tracer.set_fact(
            key="database.port",
            value="5432",
            evidence_ids=["ev-101", "ev-102"],
        )
        assert updated_fact.evidence_ref_ids == ["ev-101", "ev-102"]

    def test_assemble_state_for_prompt_compact_tokens(self) -> None:
        """Assembled prompt segment must provide compact high-density state at minimal tokens."""
        tracer = DualTrackDecisionTracer()
        tracer.set_fact("infra.node_version", "20.12.0", evidence_ids=["ev-node"])
        tracer.set_fact("infra.pnpm_version", "9.1.0", evidence_ids=["ev-pnpm"])

        assembly = tracer.assemble_state_for_prompt()

        assert assembly.active_fact_count == 2
        assert "[SYSTEM DETERMINISTIC STATE - CANONICAL TRUTH]" in assembly.state_prompt_segment
        assert "infra.node_version = 20.12.0" in assembly.state_prompt_segment
        assert "infra.pnpm_version = 9.1.0" in assembly.state_prompt_segment
        assert "[END DETERMINISTIC STATE]" in assembly.state_prompt_segment
        assert set(assembly.lazy_evidence_handles) == {"ev-node", "ev-pnpm"}
        # Token consumption is ultra-compact (< 150 tokens)
        assert assembly.estimated_tokens < 150

    def test_expand_evidence_for_fact_lazy_unrolling(self) -> None:
        """Lazy expansion retrieves full verbatim evidence only when retrospectively demanded."""
        tracer = DualTrackDecisionTracer()
        t1 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 4, 1, 10, 2, 0, tzinfo=UTC)

        ev1 = _make_evidence("ev-a", "We evaluated React vs Vue and decided on Vue 3.", timestamp=t1)
        ev2 = _make_evidence("ev-b", "Confirmed Vue 3 migration completed successfully.", timestamp=t2)

        tracer.register_evidence(ev1)
        tracer.register_evidence(ev2)

        fact = tracer.set_fact("ui.framework", "Vue 3", evidence_ids=["ev-b", "ev-a"])

        # Execute lazy unrolling
        report = tracer.expand_evidence_for_fact(fact.fact_id)

        assert report.fact_key == "ui.framework"
        assert report.fact_value == "Vue 3"
        assert len(report.matched_evidence_slices) == 2
        # Must be ordered chronologically (ev-a before ev-b)
        assert report.matched_evidence_slices[0].evidence_id == "ev-a"
        assert report.matched_evidence_slices[1].evidence_id == "ev-b"
        assert report.total_evidence_characters > 50

    def test_scope_filtering(self) -> None:
        """Tracer must respect operational scope separation."""
        tracer = DualTrackDecisionTracer()
        tracer.set_fact("auth.mode", "jwt", scope="auth_service")
        tracer.set_fact("payment.currency", "USD", scope="billing_service")

        auth_facts = tracer.list_facts(scope="auth_service")
        assert len(auth_facts) == 1
        assert auth_facts[0].key == "auth.mode"

        billing_assembly = tracer.assemble_state_for_prompt(scope="billing_service")
        assert billing_assembly.active_fact_count == 1
        assert "payment.currency = USD" in billing_assembly.state_prompt_segment
        assert "auth.mode" not in billing_assembly.state_prompt_segment

    def test_expand_nonexistent_fact_raises_keyerror(self) -> None:
        """Attempting to expand an unregistered fact must raise KeyError."""
        tracer = DualTrackDecisionTracer()
        with pytest.raises(KeyError, match="Fact 'nonexistent' does not exist"):
            tracer.expand_evidence_for_fact("nonexistent")
