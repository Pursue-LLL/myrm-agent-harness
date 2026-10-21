"""Unit tests for Enterprise Credit and Risk Ops Cockpit in myrm_agent_harness.observability.enterprise_credit_cockpit."""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.observability.enterprise_credit_cockpit import (
    CreditRiskAuditRecord,
    EnterpriseCockpitSnapshot,
    EnterpriseCreditRiskLedger,
    PolicyVerdict,
    RiskBehaviorType,
    RiskLevel,
)


def test_initial_state_and_defaults() -> None:
    """Verify that ledger initializes with default quotas and clean audit structures."""
    ledger = EnterpriseCreditRiskLedger(total_quota=50000.0)
    snapshot: EnterpriseCockpitSnapshot = ledger.get_cockpit_snapshot()

    assert snapshot.total_credit_quota == 50000.0
    assert snapshot.total_credit_spent == 0.0
    assert snapshot.available_credit == 50000.0
    assert snapshot.utilization_pct == 0.0
    assert snapshot.is_quota_breached is False
    assert snapshot.warning_threshold_pct == 80.0
    assert snapshot.total_audit_records == 0
    assert snapshot.risk_event_count == 0
    assert snapshot.blocked_count == 0

    surface_names = {a.surface_name for a in snapshot.allocations_by_surface}
    assert "webui" in surface_names
    assert "desktop" in surface_names
    assert "cloud_sandbox" in surface_names


def test_record_transaction_and_unified_audit_chain() -> None:
    """Verify that credit transactions bind Actor, Time, Data Scope, and Risk Behavior."""
    ledger = EnterpriseCreditRiskLedger(total_quota=1000.0)

    # 1. Normal query
    rec1: CreditRiskAuditRecord = ledger.record_transaction(
        actor_id="usr_alice",
        product_surface="webui",
        interaction_summary="Synthesizing tech architecture",
        data_object_scope="knowledge.docs",
        credit_consumed=15.5,
        risk_level=RiskLevel.NONE,
        risk_behavior=RiskBehaviorType.NONE,
        policy_verdict=PolicyVerdict.ALLOW,
    )
    assert rec1.actor_id == "usr_alice"
    assert rec1.product_surface == "webui"
    assert rec1.credit_consumed == 15.5
    assert rec1.risk_level == RiskLevel.NONE
    assert rec1.policy_verdict == PolicyVerdict.ALLOW

    # 2. Blocked high-risk data export
    rec2: CreditRiskAuditRecord = ledger.record_transaction(
        actor_id="usr_bob",
        product_surface="desktop",
        interaction_summary="Attempted bulk dump of customer accounts",
        data_object_scope="crm.customer_leads",
        credit_consumed=50.0,
        risk_level=RiskLevel.HIGH,
        risk_behavior=RiskBehaviorType.SENSITIVE_DATA_EXPORT,
        policy_verdict=PolicyVerdict.BLOCKED,
    )
    assert rec2.actor_id == "usr_bob"
    assert rec2.risk_level == RiskLevel.HIGH
    assert rec2.risk_behavior == RiskBehaviorType.SENSITIVE_DATA_EXPORT
    assert rec2.policy_verdict == PolicyVerdict.BLOCKED

    snapshot = ledger.get_cockpit_snapshot()
    assert snapshot.total_credit_spent == 65.5
    assert snapshot.available_credit == 934.5
    assert snapshot.total_audit_records == 2
    assert snapshot.risk_event_count == 1
    assert snapshot.blocked_count == 1
    assert snapshot.is_quota_breached is False


def test_quota_reconfiguration_and_breach() -> None:
    """Verify quota reconfiguration and breach detection."""
    ledger = EnterpriseCreditRiskLedger(total_quota=100.0)
    ledger.record_transaction(
        actor_id="usr_charlie",
        product_surface="cloud_sandbox",
        interaction_summary="Heavy agent pipeline batch run",
        data_object_scope="repos.repo_eval",
        credit_consumed=95.0,
    )

    snap1 = ledger.get_cockpit_snapshot()
    assert snap1.total_credit_spent == 95.0
    assert snap1.utilization_pct == 95.0
    assert snap1.is_quota_breached is False

    # Exceed quota
    ledger.record_transaction(
        actor_id="usr_charlie",
        product_surface="cloud_sandbox",
        interaction_summary="More pipeline steps",
        data_object_scope="repos.repo_eval",
        credit_consumed=10.0,
    )

    snap2 = ledger.get_cockpit_snapshot()
    assert snap2.total_credit_spent == 105.0
    assert snap2.available_credit == 0.0
    assert snap2.is_quota_breached is True

    # Reconfigure quota to 500.0
    ledger.configure_quota(total_quota=500.0, warning_threshold_pct=75.0)
    snap3 = ledger.get_cockpit_snapshot()
    assert snap3.total_credit_quota == 500.0
    assert snap3.available_credit == 395.0
    assert snap3.is_quota_breached is False
    assert snap3.warning_threshold_pct == 75.0


def test_audit_records_filtering() -> None:
    """Verify filtering of audit records by actor, risk level, and surface."""
    ledger = EnterpriseCreditRiskLedger()

    ledger.record_transaction(
        actor_id="usr_1",
        product_surface="webui",
        interaction_summary="Doc search",
        data_object_scope="wiki",
        credit_consumed=5.0,
        risk_level=RiskLevel.NONE,
    )
    ledger.record_transaction(
        actor_id="usr_2",
        product_surface="desktop",
        interaction_summary="Data query",
        data_object_scope="db.tables",
        credit_consumed=10.0,
        risk_level=RiskLevel.MEDIUM,
        policy_verdict=PolicyVerdict.AUDIT,
    )
    ledger.record_transaction(
        actor_id="usr_1",
        product_surface="desktop",
        interaction_summary="Secret probe",
        data_object_scope="vault.secrets",
        credit_consumed=20.0,
        risk_level=RiskLevel.CRITICAL,
        policy_verdict=PolicyVerdict.BLOCKED,
    )

    # Filter by actor_id
    usr1_records = ledger.filter_audit_records(actor_id="usr_1")
    assert len(usr1_records) == 2

    # Filter by risk_level
    critical_records = ledger.filter_audit_records(risk_level=RiskLevel.CRITICAL)
    assert len(critical_records) == 1
    assert critical_records[0].data_object_scope == "vault.secrets"

    # Filter by surface
    webui_records = ledger.filter_audit_records(surface="webui")
    assert len(webui_records) == 1
    assert webui_records[0].actor_id == "usr_1"


def test_concurrent_transactions_thread_safety() -> None:
    """Verify thread safety under heavy concurrent transactions."""
    ledger = EnterpriseCreditRiskLedger(total_quota=100000.0)

    def worker_task(i: int) -> None:
        surface = "webui" if i % 2 == 0 else "desktop"
        risk = RiskLevel.HIGH if i % 5 == 0 else RiskLevel.NONE
        verdict = PolicyVerdict.BLOCKED if risk == RiskLevel.HIGH else PolicyVerdict.ALLOW
        ledger.record_transaction(
            actor_id=f"worker_{i % 4}",
            product_surface=surface,
            interaction_summary=f"Batch query {i}",
            data_object_scope="batch.data",
            credit_consumed=10.0,
            risk_level=risk,
            policy_verdict=verdict,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker_task, range(100)))

    snap = ledger.get_cockpit_snapshot()
    assert snap.total_credit_spent == 1000.0
    assert snap.total_audit_records == 100
    assert snap.risk_event_count == 20
    assert snap.blocked_count == 20
