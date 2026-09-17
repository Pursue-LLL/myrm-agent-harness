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


def test_named_entity_guard_ignores_timestamp_colons() -> None:
    guard = NamedEntityGuard()
    # Timestamp with colons: should NOT extract 45 as port
    text = "Backup completed at 2026-09-18 10:45:00 with duration 45s."
    entities = guard.extract_entities(text)
    port_entities = [e for e in entities if e.entity_type == CriticalEntityType.PORT]
    assert len(port_entities) == 0


def test_named_entity_guard_patch_with_missing_entities() -> None:
    guard = NamedEntityGuard()
    source_texts = [
        "Postgres runs on port 5433 at 127.0.0.1 with DATABASE_URL=postgres://user:pass@127.0.0.1:5433/mydb.",
        "Configuration is in /etc/postgresql/postgresql.conf.",
    ]
    hallucinated_candidate = "Postgres is configured for debugging."

    verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=hallucinated_candidate,
        op_action="merge",
        reasoning="Combined postgres configuration.",
    )
    assert not verdict.is_valid
    assert len(verdict.missing_entities) > 0

    # Self-heal using patch_with_missing_entities
    patched = guard.patch_with_missing_entities(
        hallucinated_candidate,
        verdict.missing_entities,
    )
    assert "[保留关键实体:" in patched

    re_verdict = guard.verify_consolidation(
        source_texts=source_texts,
        consolidated_text=patched,
        op_action="merge",
        reasoning="Combined postgres configuration.",
    )
    assert re_verdict.is_valid


def test_named_entity_guard_ignores_general_uppercase_words() -> None:
    guard = NamedEntityGuard()
    # Uppercase English words or brand names without underscore, $, or = should NOT be extracted as ENV_VAR
    text = "Please run TEST before pushing to PROD. User prefers DOCKER and PYTHON over bash scripts."
    entities = guard.extract_entities(text)
    env_entities = [e for e in entities if e.entity_type == CriticalEntityType.ENV_VAR]
    assert len(env_entities) == 0

    # True env vars with underscore, $, or assignment should be extracted
    valid_text = "Set OPENAI_API_KEY=sk-test with $PORT in staging."
    valid_entities = guard.extract_entities(valid_text)
    valid_envs = {e.value for e in valid_entities if e.entity_type == CriticalEntityType.ENV_VAR}
    assert "OPENAI_API_KEY" in valid_envs
    assert "PORT" in valid_envs
