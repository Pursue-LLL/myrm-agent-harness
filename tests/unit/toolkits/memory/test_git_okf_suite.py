# [POS]: tests/unit/toolkits/memory/test_git_okf_suite.py
# [INPUT]: In-memory BM25, OKF validator, and bundle loader
# [OUTPUT]: Unit test suite validating conformance, BM25 latency, anti-tamper, and progressive disclosure

import datetime
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    GovernanceLevel,
    InMemoryBM25Searcher,
    OKFBundleLoader,
    OKFConcept,
    OKFConceptValidator,
    OKFGenerated,
    OKFVerified,
)


def test_in_memory_bm25_search_scoring_and_filtering() -> None:
    """Test in-memory BM25 lexical ranking, field weighting, and sub-millisecond latency."""
    searcher = InMemoryBM25Searcher()

    c1 = OKFConcept(
        id="conventions/auth-guard",
        path="conventions/auth-guard.md",
        type="rule",
        title="Authentication Guardrails",
        description="Mandatory JWT authentication token validation for all APIs",
        governance=GovernanceLevel.CONSTRAINT,
        code_refs=["src/api/auth/**"],
        tags=["auth", "security"],
        body="All incoming REST endpoints must verify bearer token validity.",
    )
    c2 = OKFConcept(
        id="arch/storage-sqlite",
        path="arch/storage-sqlite.md",
        type="architecture",
        title="SQLite Storage Architecture",
        description="Local-first persistence using SQLite with FTS5",
        governance=GovernanceLevel.CONTEXT,
        code_refs=["src/storage/**"],
        tags=["sqlite", "database"],
        body="We use SQLite as embedded storage without remote database requirements.",
    )

    searcher.index([c1, c2])

    t0 = time.perf_counter()
    results = searcher.search(query="JWT bearer authentication", limit=5)
    t_elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(results) == 1
    assert results[0].concept_id == "conventions/auth-guard"
    assert "title" in results[0].matched_fields or "description" in results[0].matched_fields
    assert t_elapsed_ms < 5.0, f"BM25 latency exceeded threshold: {t_elapsed_ms:.3f}ms"

    # Governance filter check
    gov_results = searcher.search(query="SQLite", filter_governance="context")
    assert len(gov_results) == 1
    assert gov_results[0].concept_id == "arch/storage-sqlite"

    empty_results = searcher.search(query="SQLite", filter_governance="constraint")
    assert len(empty_results) == 0


def test_okf_validator_stale_and_cwe22_security_guard() -> None:
    """Test explicit shelf-life (stale_after) expiration and CWE-22 path traversal prevention."""
    validator = OKFConceptValidator()
    today = datetime.date(2026, 10, 8)

    # 1. Stale concept test
    stale_concept = OKFConcept(
        id="temp/v1-migration",
        path="temp/v1-migration.md",
        type="rule",
        stale_after="2026-09-01",
    )
    assert validator.is_concept_stale(stale_concept, reference_date=today) is True

    valid_concept = OKFConcept(
        id="temp/v2-migration",
        path="temp/v2-migration.md",
        type="rule",
        stale_after="2026-12-31",
    )
    assert validator.is_concept_stale(valid_concept, reference_date=today) is False

    # 2. Path Traversal (CWE-22) test
    traversal_concept = OKFConcept(
        id="security/dangerous-ref",
        path="security/dangerous-ref.md",
        type="rule",
        code_refs=["../../etc/passwd", "/absolute/system/path"],
    )

    report = validator.validate([traversal_concept], reference_date=today)
    assert report.is_conformant is True  # No structural syntax errors
    assert report.gate_passed is False   # Blocked by gate findings
    assert any(".." in finding for finding in report.gate_findings)
    assert any("must be a relative" in finding for finding in report.gate_findings)


def test_okf_validator_superseded_trust_anti_tamper() -> None:
    """Test human-agent trust balance and anti-tamper superseded verification detection."""
    validator = OKFConceptValidator()

    # Agent generated modification AFTER human verified -> superseded!
    tampered_concept = OKFConcept(
        id="conventions/code-style",
        path="conventions/code-style.md",
        type="rule",
        generated=OKFGenerated(by="agent/myrm-v2", at="2026-10-05T12:00:00Z"),
        verified=[OKFVerified(by="human/alice", at="2026-10-01T10:00:00Z")],
    )

    report = validator.validate([tampered_concept])
    assert report.gate_passed is False
    assert report.superseded_trust_count == 1
    assert any("superseded verification" in finding for finding in report.gate_findings)

    # Human verified AFTER agent generated -> valid trust
    verified_concept = OKFConcept(
        id="conventions/code-style",
        path="conventions/code-style.md",
        type="rule",
        generated=OKFGenerated(by="agent/myrm-v2", at="2026-10-05T12:00:00Z"),
        verified=[OKFVerified(by="human/alice", at="2026-10-06T10:00:00Z")],
    )

    report_valid = validator.validate([verified_concept])
    assert report_valid.gate_passed is True
    assert report_valid.superseded_trust_count == 0


def test_bundle_loader_two_phase_progressive_disclosure(tmp_path: Path) -> None:
    """Test end-to-end bundle scanning, two-phase progressive disclosure, and BM25 search."""
    bundle_dir = tmp_path / "knowledge"
    bundle_dir.mkdir()

    # 1. Create root index.md (catalog)
    (bundle_dir / "index.md").write_text("# Knowledge Catalog\nBundle overview", encoding="utf-8")

    # 2. Create concept files with YAML frontmatter
    c1_dir = bundle_dir / "conventions"
    c1_dir.mkdir()
    (c1_dir / "security.md").write_text(
        """---
type: rule
title: Security Standards
description: Mandatory zero-trust network policy
governance: constraint
status: stable
stale_after: 2026-12-31
code_refs:
  - src/net/**
tags:
  - security
  - net
generated:
  by: agent/myrm
  at: "2026-10-01T00:00:00Z"
verified:
  - by: human/alice
    at: "2026-10-02T00:00:00Z"
---
# Security Standards Body
All outbound connections must pass proxy filters.
""",
        encoding="utf-8",
    )

    (bundle_dir / "overview.md").write_text(
        """---
type: architecture
title: System Overview
description: High-level overview of project subsystems
governance: context
status: stable
stale_after: 2026-01-01
---
# Project Overview
High level architectural topology.
""",
        encoding="utf-8",
    )

    loader = OKFBundleLoader(bundle_dir)
    loaded_count = loader.load_bundle()
    assert loaded_count == 2

    # Phase 1: Progressive Disclosure Summary
    summary = loader.get_disclosure_summary()
    assert summary.total_concepts == 2
    assert summary.stale_count == 1  # overview.md expired on 2026-01-01
    assert len(summary.concepts) == 2

    sec_summary = next(c for c in summary.concepts if c.id == "conventions/security")
    assert sec_summary.governance == "constraint"
    assert sec_summary.is_stale is False
    assert sec_summary.code_refs == ["src/net/**"]

    # Phase 2: On-demand full card fetch
    full_concept = loader.get_concept("conventions/security")
    assert full_concept is not None
    assert "proxy filters" in full_concept.body
    assert len(full_concept.verified) == 1

    # In-memory BM25 Search
    hits = loader.search(query="zero-trust network proxy")
    assert len(hits) >= 1
    assert hits[0].concept_id == "conventions/security"
    assert hits[0].is_stale is False

    # Validation
    val_report = loader.validate()
    assert val_report.is_conformant is True
    assert val_report.stale_count == 1
