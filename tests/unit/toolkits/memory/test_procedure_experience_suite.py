# [POS]: tests/unit/toolkits/memory/test_procedure_experience_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.procedure_experience
# [OUTPUT]: Unit tests for ProcedureShapedExperienceProtocolAndFixedCountDualNodeRetrievalSuite (Item 104)

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    DualNodeFixedCountRetriever,
    DualNodeRetrievalQuery,
    ProcedureMemoryEntry,
    ProcedureProtocolEngine,
    RetrievalNodeKind,
)


def test_procedure_protocol_validation_and_anchor_synthesis() -> None:
    """Validate 8-field procedure protocol completeness and compact retrieval anchor generation."""
    engine = ProcedureProtocolEngine()

    # Incomplete entry missing anti_patterns and negative_applicability
    incomplete_entry = ProcedureMemoryEntry(
        entry_id="proc-err-01",
        name="Broken Procedure",
        retrieval_anchor="",
        operation_intent="Migrate database without downtime",
        preconditions=["Postgres 16 running"],
        immutable_boundary=["User table primary keys"],
        procedure_steps=["1. Add column", "2. Backfill async", "3. Switch read traffic"],
        write_field_provenance={"db_version": "Calculated from schema migrator"},
        anti_patterns=[],  # empty!
        applicability=["Relational schema upgrades"],
        negative_applicability=[],  # empty!
    )
    violations = engine.validate_protocol(incomplete_entry)
    assert len(violations) == 2
    assert any("anti_patterns" in v for v in violations)
    assert any("negative_applicability" in v for v in violations)

    # Valid complete entry
    valid_entry = ProcedureMemoryEntry(
        entry_id="proc-valid-01",
        name="Zero Downtime Column Migration",
        retrieval_anchor="",
        operation_intent="Migrate database column schema without service downtime",
        preconditions=["PostgreSQL 16 connection established", "Target volume mounted"],
        immutable_boundary=["Raw user identities", "Historical audit ledger"],
        procedure_steps=[
            "1. Run idempotent DDL adding nullable column",
            "2. Backfill historical records in micro-batches of 100",
            "3. Enforce not-null constraint with validation gate",
        ],
        write_field_provenance={"column_hash": "SHA-256 of migration script"},
        anti_patterns=["Do not run lock-table DDL inside single monolithic transaction"],
        applicability=["Production schema alteration", "Relational migrations"],
        negative_applicability=["Non-relational Qdrant vector collection reshaping"],
    )
    assert len(engine.validate_protocol(valid_entry)) == 0

    # Test anchor generation
    anchor = engine.generate_retrieval_anchor(
        operation_intent=valid_entry.operation_intent,
        preconditions=valid_entry.preconditions,
        applicability=valid_entry.applicability,
    )
    assert "intent:" in anchor
    assert "pre:" in anchor
    assert "app:" in anchor
    assert "migrate" in anchor or "database" in anchor

    # Test multi-intent decomposition
    composite_text = """
### Intent: Add Schema Column
Step 1: Check connectivity
Step 2: Alter table

### Intent: Backfill Table Rows
Step 1: Query unmigrated cursor
Step 2: Update in batches
"""
    fragments = engine.split_multi_intent_raw_steps(composite_text)
    assert len(fragments) == 2
    assert "Add Schema Column" in fragments[0]["intent"]
    assert "Backfill Table Rows" in fragments[1]["intent"]


def test_dual_node_fixed_count_retrieval() -> None:
    """Validate fixed-count retrieval at FIRST_USER and PRE_WRITE nodes without character budget collapse."""
    retriever = DualNodeFixedCountRetriever()

    # Entry 1: Schema migration
    e1 = ProcedureMemoryEntry(
        entry_id="proc-schema-01",
        name="Zero Downtime Column Migration",
        retrieval_anchor="",
        operation_intent="Migrate database column schema without service downtime",
        preconditions=["PostgreSQL 16 connection established", "Target volume mounted"],
        immutable_boundary=["Raw user identities", "Historical audit ledger"],
        procedure_steps=["1. Add nullable column", "2. Backfill in batches"],
        write_field_provenance={"column_hash": "SHA-256 of migration script"},
        anti_patterns=["Do not run lock-table DDL in monolithic transaction"],
        applicability=["Production schema alteration", "Relational migrations"],
        negative_applicability=["Vector collection reshaping"],
        confidence=1.0,
    )

    # Entry 2: Refactoring with strict types
    e2 = ProcedureMemoryEntry(
        entry_id="proc-refactor-02",
        name="Strict Type Refactoring Protocol",
        retrieval_anchor="",
        operation_intent="Refactor legacy modules enforcing concrete Type Hints and zero Any",
        preconditions=["Ruff and mypy configured in workspace"],
        immutable_boundary=["Core public API contracts", "Backward compatibility baselines"],
        procedure_steps=["1. Identify untyped signatures", "2. Replace Any with Union/Generics"],
        write_field_provenance={"type_annotation": "Resolved from concrete domain models"},
        anti_patterns=["Never cast to Any to silence lint errors"],
        applicability=["Codebase maintenance", "Python PEP8 typing conformance"],
        negative_applicability=["Prototyping dynamic monkey-patched scripts"],
        confidence=0.95,
    )

    retriever.register(e1)
    retriever.register(e2)

    # Query 1: FIRST_USER node (focus on user prompt intent: database schema)
    q_first = DualNodeRetrievalQuery(
        query_text="We need to update our database schema for users",
        node_kind=RetrievalNodeKind.FIRST_USER,
        top_n=2,
    )
    res_first = retriever.retrieve(q_first)
    assert res_first.node_kind == RetrievalNodeKind.FIRST_USER
    assert len(res_first.matched_entries) >= 1
    assert res_first.matched_entries[0].entry_id == "proc-schema-01"

    # Query 2: PRE_WRITE node (focus on write file action / immutable boundaries / anti-patterns)
    q_write = DualNodeRetrievalQuery(
        query_text="Applying code edits to models, avoid casting to Any and protect core API",
        node_kind=RetrievalNodeKind.PRE_WRITE,
        top_n=1,
    )
    res_write = retriever.retrieve(q_write)
    assert res_write.node_kind == RetrievalNodeKind.PRE_WRITE
    # Must strictly adhere to top_n=1 fixed-count
    assert len(res_write.matched_entries) == 1
    assert res_write.matched_entries[0].entry_id == "proc-refactor-02"
    assert "Never cast to Any" in res_write.matched_entries[0].anti_patterns[0]


def test_protocol_violation_raises_error() -> None:
    """Validate that registering an incomplete entry raises ValueError."""
    retriever = DualNodeFixedCountRetriever()
    broken_entry = ProcedureMemoryEntry(
        entry_id="proc-fail",
        name="Missing fields",
        retrieval_anchor="",
        operation_intent="",
    )
    with pytest.raises(ValueError, match="protocol violation"):
        retriever.register(broken_entry)
