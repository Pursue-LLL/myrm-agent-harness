"""Unit tests for cross-session handoff contract synthesizer and continuity ledger."""

import os
import shutil
import tempfile
import time
from collections.abc import Generator

import pytest

from myrm_agent_harness.runtime.context.cross_session_handoff_ledger import (
    CrossSessionHandoffLedger,
)
from myrm_agent_harness.runtime.context.cross_session_handoff_types import (
    CrossSessionHandoffContract,
    HandoffDecisionItem,
    HandoffPitfallItem,
    HandoffStatus,
    HandoffTodoItem,
    SessionLifecyclePhase,
)
from myrm_agent_harness.runtime.context.rule_based_session_synthesizer import (
    RuleBasedSessionSynthesizer,
)


@pytest.fixture
def temp_persistence_dir() -> Generator[str]:
    """Temporary storage directory for testing disk persistence."""
    tmp = tempfile.mkdtemp(prefix="test_handoff_ledger_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_rule_based_session_synthesizer() -> None:
    """Test deterministic rule-based fact extraction from conversation turns."""
    synthesizer = RuleBasedSessionSynthesizer(agent_profile="fullstack_agent")

    mock_turns = [
        {
            "role": "user",
            "content": "Please refactor the billing service and add test coverage.",
        },
        {
            "role": "assistant",
            "content": (
                "[Decision] We will use Decimal instead of float for currency precision.\n\n"
                "I will now inspect the source file."
            ),
            "tool_calls": [
                {
                    "name": "write_to_file",
                    "arguments": {"TargetFile": "/app/services/billing.py"},
                },
                {
                    "name": "run_command",
                    "arguments": {"CommandLine": "pytest tests/test_billing.py"},
                },
            ],
        },
        {
            "role": "tool",
            "tool_name": "run_command",
            "tool_output": "Error: connection timeout to PostgreSQL during migration",
        },
        {
            "role": "assistant",
            "content": (
                "Billing refactored.\n"
                "- [ ] Add integration test with mock database\n"
                "TODO: Update README with the new payment gateway API\n"
            ),
        },
    ]

    contract = synthesizer.synthesize_from_records(
        session_id="session-xyz-12345",
        turn_records=mock_turns,
        task_summary="Refactor billing service",
    )

    assert contract.source_session_id == "session-xyz-12345"
    assert contract.source_agent_profile == "fullstack_agent"
    assert "/app/services/billing.py" in contract.touched_files
    assert "pytest tests/test_billing.py" in contract.executed_commands_summary

    # Verify extracted decisions
    assert len(contract.decisions) == 1
    assert "Decimal instead of float" in contract.decisions[0].rationale

    # Verify extracted TODOs
    assert len(contract.todos) == 2
    assert any("integration test" in t.description for t in contract.todos)
    assert any("Update README" in t.description for t in contract.todos)

    # Verify extracted pitfalls
    assert len(contract.pitfalls) == 1
    assert "connection timeout" in contract.pitfalls[0].recommendation


def test_cross_session_handoff_ledger_lifecycle_and_single_consumption() -> None:
    """Test registration, pending listing, and single-consumer state transition."""
    ledger = CrossSessionHandoffLedger()

    contract = CrossSessionHandoffContract(
        handoff_id="HDF-001",
        source_session_id="session-A",
        created_at=time.time(),
        source_agent_profile="backend_dev",
        target_task_summary="Complete user auth middleware",
        decisions=[
            HandoffDecisionItem(
                decision_id="DEC-1",
                topic="JWT Validation",
                rationale="Use RS256 asymmetric keys",
                timestamp=time.time(),
            )
        ],
        todos=[
            HandoffTodoItem(
                task_id="TODO-1",
                description="Implement token refresh endpoint",
                priority="P0",
                is_completed=False,
            )
        ],
        pitfalls=[
            HandoffPitfallItem(
                warning_id="PIT-1",
                context="Token validation",
                recommendation="Ensure clock skew tolerance of 60s",
            )
        ],
        touched_files=["auth/middleware.py"],
        executed_commands_summary=["pip install pyjwt"],
    )

    ledger.register_handoff(contract)

    # Check pending list
    pending = ledger.list_pending_handoffs("session-A")
    assert len(pending) == 1
    assert pending[0].handoff_id == "HDF-001"

    # Consume for session-B
    consumed, receipt = ledger.consume_handoff(
        handoff_id="HDF-001",
        consumer_session_id="session-B",
    )
    assert consumed is not None
    assert receipt is not None
    assert consumed.status == HandoffStatus.CONSUMED
    assert consumed.consumed_by_session_id == "session-B"
    assert receipt.active_todos_count == 1
    assert receipt.injected_prompt_tokens_est > 0

    # Ensure second consumer attempt fails atomically
    consumed_second, receipt_second = ledger.consume_handoff(
        handoff_id="HDF-001",
        consumer_session_id="session-C",
    )
    assert consumed_second is None
    assert receipt_second is None

    # Check pending list is now empty
    assert len(ledger.list_pending_handoffs("session-A")) == 0


def test_handoff_prompt_block_rendering() -> None:
    """Test rendering structured markdown handoff contract prompt block."""
    ledger = CrossSessionHandoffLedger()
    contract = CrossSessionHandoffContract(
        handoff_id="HDF-TEST-PROMPT",
        source_session_id="session-upstream",
        created_at=time.time(),
        source_agent_profile="architect",
        target_task_summary="Refactor storage engine",
        decisions=[
            HandoffDecisionItem(
                decision_id="DEC-01",
                topic="Storage backend",
                rationale="Adopt SQLite with WAL mode",
                timestamp=time.time(),
            )
        ],
        todos=[
            HandoffTodoItem(
                task_id="TODO-01",
                description="Write migration script",
                priority="P1",
                is_completed=False,
            )
        ],
        pitfalls=[
            HandoffPitfallItem(
                warning_id="PIT-01",
                context="SQLite lock",
                recommendation="Set busy_timeout to 5000ms",
            )
        ],
        touched_files=["storage/db.py", "storage/schema.sql"],
        executed_commands_summary=["sqlite3 test.db < schema.sql"],
    )

    rendered = ledger.render_handoff_prompt_block(contract)
    assert "<session_handoff_contract id=\"HDF-TEST-PROMPT\"" in rendered
    assert "<summary>Refactor storage engine</summary>" in rendered
    assert "<decision id=\"DEC-01\"" in rendered
    assert "<todo id=\"TODO-01\"" in rendered
    assert "<pitfall id=\"PIT-01\"" in rendered
    assert "`storage/db.py`" in rendered
    assert "sqlite3 test.db < schema.sql" in rendered


def test_handoff_expiration_filtering() -> None:
    """Test that expired handoff contracts are automatically filtered out."""
    ledger = CrossSessionHandoffLedger()
    old_timestamp = time.time() - 1000

    expired_contract = CrossSessionHandoffContract(
        handoff_id="HDF-OLD",
        source_session_id="session-old",
        created_at=old_timestamp,
        source_agent_profile="agent",
        target_task_summary="Old task",
        ttl_seconds=500,  # Expired
    )

    ledger.register_handoff(expired_contract)

    # list_pending_handoffs should filter it out and mark EXPIRED
    pending = ledger.list_pending_handoffs()
    assert len(pending) == 0

    contract_in_store = ledger.get_handoff("HDF-OLD")
    assert contract_in_store is not None
    assert contract_in_store.status == HandoffStatus.EXPIRED


def test_disk_persistence_and_reload(temp_persistence_dir: str) -> None:
    """Test disk JSONL serialization and reload across ledger instances."""
    persisted_path = os.path.join(temp_persistence_dir, "handoffs.jsonl")
    ledger1 = CrossSessionHandoffLedger(persistence_file=persisted_path)

    contract = CrossSessionHandoffContract(
        handoff_id="HDF-PERSIST-1",
        source_session_id="session-alpha",
        created_at=time.time(),
        source_agent_profile="dev",
        target_task_summary="Build telemetry reporter",
        touched_files=["telemetry.py"],
    )
    ledger1.register_handoff(contract)

    # Initialize a new ledger instance pointing to the same file
    ledger2 = CrossSessionHandoffLedger(persistence_file=persisted_path)
    loaded = ledger2.get_handoff("HDF-PERSIST-1")
    assert loaded is not None
    assert loaded.source_session_id == "session-alpha"
    assert loaded.touched_files == ["telemetry.py"]
    assert loaded.status == HandoffStatus.PENDING

    # Finalize session check
    phase = ledger2.finalize_session("session-alpha")
    assert phase == SessionLifecyclePhase.FINALIZED
