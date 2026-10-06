"""Unit tests for evidence-based locator grounding protocol and anti-hallucination gate."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.evidence_grounding_gate import (
    EvidenceGroundingProtocolHub,
)
from myrm_agent_harness.runtime.context.evidence_grounding_types import (
    LocatorKind,
    StructuredLocator,
)


@pytest.fixture
def hub() -> EvidenceGroundingProtocolHub:
    return EvidenceGroundingProtocolHub()


def test_structured_locator_display_formats() -> None:
    """Validate string rendering of line ranges, primary keys, and char offset locators."""
    loc_lines = StructuredLocator(kind=LocatorKind.LINE_RANGE, line_range=(10, 25))
    assert loc_lines.to_display_string() == "L10-L25"

    loc_pk = StructuredLocator(
        kind=LocatorKind.PRIMARY_KEY,
        key_fields={"id": "usr_99", "tenant": "prod_us"},
    )
    assert loc_pk.to_display_string() == "pk(id=usr_99,tenant=prod_us)"

    loc_chars = StructuredLocator(kind=LocatorKind.CHAR_OFFSET, char_range=(100, 350))
    assert loc_chars.to_display_string() == "chars(100-350)"


def test_search_candidate_registration(hub: EvidenceGroundingProtocolHub) -> None:
    """Validate registering candidate hits carrying structured locators."""
    loc = StructuredLocator(kind=LocatorKind.LINE_RANGE, line_range=(50, 65))
    hit = hub.register_search_candidate(
        source_uri="repo://src/auth/jwt.py",
        locator=loc,
        snippet_preview="def verify_jwt_token(token: str) -> bool: ...",
        score=0.92,
    )
    assert hit.hit_id.startswith("hit_")
    assert not hit.is_verified
    assert hit.source_uri == "repo://src/auth/jwt.py"


def test_mandatory_evidence_browse_and_hash_verification(
    hub: EvidenceGroundingProtocolHub,
) -> None:
    """Validate Search->Locate->Browse workflow: re-reading authentic object content."""
    loc = StructuredLocator(kind=LocatorKind.LINE_RANGE, line_range=(12, 16))
    hit = hub.register_search_candidate(
        source_uri="file:///workspace/config.yaml",
        locator=loc,
        snippet_preview="database: postgresql://...",
    )

    canonical_storage = {
        "file:///workspace/config.yaml": "database:\n  driver: postgresql\n  pool_size: 20\n  timeout: 30\n",
    }

    def mock_fetcher(uri: str, _locator: StructuredLocator) -> str:
        return canonical_storage[uri]

    verified = hub.browse_evidence(hit.hit_id, mock_fetcher)

    assert verified.evidence_id.startswith("ev_")
    assert verified.hit_id == hit.hit_id
    assert "pool_size: 20" in verified.raw_content
    assert len(verified.content_hash) == 16

    # Verify that the hit itself is now marked verified
    re_fetched = hub.get_verified_evidence(verified.evidence_id)
    assert re_fetched is not None
    assert re_fetched.evidence_id == verified.evidence_id


def test_anti_hallucination_grounding_gate_success(hub: EvidenceGroundingProtocolHub) -> None:
    """Validate grounding audit passes when claims cite authentic, verified evidence."""
    loc = StructuredLocator(kind=LocatorKind.LINE_RANGE, line_range=(1, 5))
    hit = hub.register_search_candidate(
        source_uri="file:///docs/arch.md",
        locator=loc,
        snippet_preview="Architecture design note",
    )

    verified = hub.browse_evidence(
        hit.hit_id,
        lambda _uri, _loc: "Architecture overview: microkernel design with pluggable subsystems.",
    )

    answer = "The system uses a microkernel architecture with pluggable subsystems for flexibility."
    audit = hub.audit_grounding([verified.evidence_id], answer)

    assert audit.is_grounded
    assert audit.total_claims_count == 1
    assert audit.grounded_claims_count == 1
    assert len(audit.missing_evidence_reasons) == 0
    assert audit.confidence_score == 1.0

    # Validate citation formatting
    citation = hub.format_grounded_citation(verified.evidence_id)
    assert f"[Evidence #{verified.evidence_id}]" in citation
    assert "file:///docs/arch.md#L1-L5" in citation


def test_anti_hallucination_grounding_gate_rejections(
    hub: EvidenceGroundingProtocolHub,
) -> None:
    """Validate that unverified citations, forged IDs, and zero-overlap claims are rejected."""
    # Case A: Citing non-existent evidence ID
    audit_fake = hub.audit_grounding(["ev_nonexistent_id"], "Some claims here.")
    assert not audit_fake.is_grounded
    assert any("non-existent" in r for r in audit_fake.missing_evidence_reasons)

    # Case B: Substantial answer without citing any evidence
    substantial_answer = (
        "The system has been completely restructured to use Redis Streams for all event brokering "
        "and Kafka for high-throughput stream processing across regional clusters."
    )
    audit_uncited = hub.audit_grounding([], substantial_answer)
    assert not audit_uncited.is_grounded
    assert any("without citing any verified evidence" in r for r in audit_uncited.missing_evidence_reasons)

    # Case C: Cited evidence has zero lexical overlap with answer
    hit = hub.register_search_candidate(
        source_uri="file:///finance.txt",
        locator=StructuredLocator(kind=LocatorKind.LINE_RANGE, line_range=(1, 2)),
        snippet_preview="Quarterly revenue figures",
    )
    verified = hub.browse_evidence(
        hit.hit_id,
        lambda _uri, _loc: "Revenue report: Q3 profit reached fifteen million dollars.",
    )

    irrelevant_answer = "The database cluster experienced network partition failure at timestamp 400."
    audit_mismatch = hub.audit_grounding([verified.evidence_id], irrelevant_answer)
    assert not audit_mismatch.is_grounded
    assert any("insufficient lexical overlap" in r for r in audit_mismatch.missing_evidence_reasons)
