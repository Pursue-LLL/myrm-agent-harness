"""Unit tests for deterministic NamedEntityGuard."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.named_entity_guard import (
    CriticalEntityType,
    NamedEntityGuard,
)


def test_named_entity_guard_extracts_ports_ips_env_and_paths() -> None:
    guard = NamedEntityGuard()
    text = (
        "Postgres runs on port 5433 at 127.0.0.1 with DATABASE_URL=postgres://user:pass@127.0.0.1:5433/mydb. "
        "The configuration file is located at /etc/postgresql/postgresql.conf."
    )
    entities = guard.extract_entities(text)
    types = {e.entity_type for e in entities}
    values = {e.value for e in entities}

    assert CriticalEntityType.PORT in types
    assert "5433" in values
    assert CriticalEntityType.IP_ADDRESS in types
    assert "127.0.0.1" in values
    assert CriticalEntityType.ENV_VAR in types
    assert "DATABASE_URL" in values
    assert CriticalEntityType.FILE_PATH in types
    assert "/etc/postgresql/postgresql.conf" in values


def test_named_entity_guard_rejects_silent_port_loss() -> None:
    guard = NamedEntityGuard()
    source_texts = [
        "User specified that postgres runs on port 5433 for local debugging.",
        "Postgres database is accessed at 127.0.0.1.",
    ]
    # LLM merges and hallucinates/drops the port 5433 (e.g. generalizes to standard 5432 or drops it)
    hallucinated_candidate = "User accesses postgres database at 127.0.0.1:5432."

    verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=hallucinated_candidate,
        op_action="merge",
        reasoning="Combined postgres access instructions.",
    )

    assert not verdict.is_valid
    assert verdict.rejection_code == "CRITICAL_ENTITY_LOST_PORT"
    assert any(e.value == "5433" for e in verdict.missing_entities)


def test_named_entity_guard_allows_preservation() -> None:
    guard = NamedEntityGuard()
    source_texts = [
        "User specified that postgres runs on port 5433 for local debugging.",
        "Postgres database is accessed at 127.0.0.1.",
    ]
    faithful_candidate = "Postgres database runs at 127.0.0.1 on port 5433 for local debugging."

    verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=faithful_candidate,
        op_action="merge",
        reasoning="Combined postgres configuration.",
    )

    assert verdict.is_valid
    assert verdict.rejection_code is None
    assert len(verdict.missing_entities) == 0


def test_named_entity_guard_allows_justified_correction() -> None:
    guard = NamedEntityGuard()
    source_texts = [
        "Service was running on port 8080.",
    ]
    # LLM explicitly corrects 8080 to 9090 with reasoning explaining why 8080 was superseded
    corrected_candidate = "Service has been migrated to run on port 9090."

    verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=corrected_candidate,
        op_action="correct",
        reasoning="User explicitly instructed to change port 8080 to 9090 due to port conflict.",
    )

    assert verdict.is_valid
    assert len(verdict.missing_entities) == 0


def test_named_entity_guard_passes_when_no_technical_entities() -> None:
    guard = NamedEntityGuard()
    source_texts = [
        "User prefers concise responses.",
        "User likes reading code examples first.",
    ]
    candidate = "User prefers concise answers with code examples up front."

    verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=candidate,
        op_action="merge",
        reasoning="Merged communication preferences.",
    )

    assert verdict.is_valid
