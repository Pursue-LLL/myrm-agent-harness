"""Unit tests for Negative Decision Ledger and Anti-Regression Protection Guard.

Part of Item 129: NegativeDecisionAndRejectionReasonLedger.
Verifies recording failed attempts, uncompressible prompt constraints compilation,
pre-flight plan regression interception, pattern matching, and thread safety.
"""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.runtime.context.negative_decision_ledger import (
    NegativeDecisionLedger,
)
from myrm_agent_harness.runtime.context.negative_decision_ledger_types import (
    FailureRootCauseKind,
)


def test_record_rejection_and_retrieval() -> None:
    """Verify recording rejected decisions and session filtering."""
    ledger = NegativeDecisionLedger()

    entry1 = ledger.record_rejection(
        session_id="sess-001",
        attempted_solution="Use monkeypatch on sys.modules to mock cryptography",
        root_cause_kind=FailureRootCauseKind.RUNTIME_EXCEPTION,
        rejection_reason="Causes global state corruption and C-extension segfault",
        associated_files=["src/security/crypto.py"],
        disqualified_patterns=["sys.modules['cryptography']"],
        tried_turn=3,
    )
    assert entry1.session_id == "sess-001"
    assert entry1.root_cause_kind == FailureRootCauseKind.RUNTIME_EXCEPTION
    assert entry1.tried_turn == 3

    ledger.record_rejection(
        session_id="sess-002",
        attempted_solution="Disable SSL certificate validation on outbound proxy",
        root_cause_kind=FailureRootCauseKind.SECURITY_VIOLATION,
        rejection_reason="Violates HIPAA & SOC2 enterprise compliance gate",
        disqualified_patterns=["verify=False", "insecure_skip_verify"],
    )

    all_entries = ledger.get_entries()
    assert len(all_entries) == 2

    filtered = ledger.get_entries(session_id="sess-001")
    assert len(filtered) == 1
    assert filtered[0].entry_id == entry1.entry_id


def test_compile_protected_negative_constraints() -> None:
    """Verify compilation of immutable uncompressible markdown constraints block."""
    ledger = NegativeDecisionLedger()
    ledger.record_rejection(
        session_id="sess-compile",
        attempted_solution="Adopt deprecated pydantic v1 parse_obj pattern",
        root_cause_kind=FailureRootCauseKind.COMPILATION_ERROR,
        rejection_reason="Framework strictly standardized on Pydantic v2 model_validate",
        associated_files=["src/schemas/user.py"],
        disqualified_patterns=["parse_obj"],
    )

    rendered = ledger.compile_protected_negative_constraints(session_id="sess-compile")
    assert "<forbidden_anti_regression_constraints>" in rendered
    assert "</forbidden_anti_regression_constraints>" in rendered
    assert "DO NOT RETRY these solutions" in rendered
    assert "Adopt deprecated pydantic v1 parse_obj pattern" in rendered
    assert "compilation_error" in rendered
    assert "parse_obj" in rendered


def test_anti_regression_plan_interception_pattern_match() -> None:
    """Verify interception triggers when proposed plan contains forbidden patterns."""
    ledger = NegativeDecisionLedger()
    ledger.record_rejection(
        session_id="sess-guard",
        attempted_solution="Direct SQLite raw connection with auto-commit",
        root_cause_kind=FailureRootCauseKind.RUNTIME_EXCEPTION,
        rejection_reason="Bypasses WAL mode and transactional locking barrier",
        disqualified_patterns=["isolation_level=None", "autocommit=True"],
    )

    # 1. Plan with forbidden pattern -> Intercepted
    bad_plan = "We will open sqlite3.connect('app.db', isolation_level=None) to run migrations"
    res_bad = ledger.check_plan_regression(proposed_plan=bad_plan, session_id="sess-guard")
    assert res_bad.is_blocked is True
    assert res_bad.matched_entry is not None
    assert "isolation_level=None" in res_bad.reason

    # 2. Plan without forbidden pattern -> Passed
    good_plan = "We will use SQLAlchemy async session with strict transaction boundary"
    res_good = ledger.check_plan_regression(proposed_plan=good_plan, session_id="sess-guard")
    assert res_good.is_blocked is False


def test_anti_regression_plan_interception_semantic_and_file_match() -> None:
    """Verify interception triggers when plan description semantically matches with target files."""
    ledger = NegativeDecisionLedger()
    ledger.record_rejection(
        session_id="sess-file",
        attempted_solution="Refactor authentication token parsing using base64 decoding",
        root_cause_kind=FailureRootCauseKind.USER_EXPLICIT_REJECTION,
        rejection_reason="User expressly forbade base64 parsing due to payload tampering risk",
        associated_files=["src/auth/token_parser.py"],
    )

    # Repeating similar approach on the same file -> Blocked
    similar_plan = "Let's refactor authentication token parsing using base64 decoding approach"
    res_blocked = ledger.check_plan_regression(
        proposed_plan=similar_plan,
        target_files=["src/auth/token_parser.py"],
        session_id="sess-file",
    )
    assert res_blocked.is_blocked is True
    assert "re-attempts previously failed solution" in res_blocked.reason

    # Completely different approach on different file -> Passed
    different_plan = "Implement Ed25519 cryptographic token verification"
    res_passed = ledger.check_plan_regression(
        proposed_plan=different_plan,
        target_files=["src/auth/ed25519_verifier.py"],
        session_id="sess-file",
    )
    assert res_passed.is_blocked is False


def test_multithreaded_concurrency_safety() -> None:
    """Verify thread-safe concurrent rejection writes and pre-flight plan checks."""
    ledger = NegativeDecisionLedger()

    def worker(worker_id: int) -> None:
        for idx in range(15):
            ledger.record_rejection(
                session_id=f"sess-worker-{worker_id}",
                attempted_solution=f"Solution {worker_id}-{idx}",
                root_cause_kind=FailureRootCauseKind.PERFORMANCE_DEGRADATION,
                rejection_reason=f"Latency spike {idx}ms",
                disqualified_patterns=[f"bad_flag_{worker_id}_{idx}"],
            )
            res = ledger.check_plan_regression(
                proposed_plan=f"Use bad_flag_{worker_id}_{idx} in pipeline",
                session_id=f"sess-worker-{worker_id}",
            )
            assert res.is_blocked is True

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(16)]
        concurrent.futures.wait(futures)

    assert len(ledger.get_entries()) == 16 * 15
