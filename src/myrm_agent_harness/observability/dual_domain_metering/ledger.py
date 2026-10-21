"""
[INPUT]: Itemized domain records and summary calculation requests.
[OUTPUT]: Thread-safe DualDomainMeteringLedger managing records and reconciliation statements.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/dual_domain_metering/ledger.py
"""

from collections import defaultdict
import threading
import time
from typing import Dict, List, Optional
import uuid

from .models import (
    DomainMeteringRecord,
    MeteringDomain,
    ReconciliationStatement,
    SessionDualDomainSummary,
    ThreeDimensionalCost,
)


class DualDomainMeteringLedger:
    """Thread-safe ledger separating gateway interaction domain from sandbox execution domain."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records_by_session: Dict[str, List[DomainMeteringRecord]] = defaultdict(list)
        self._statements: Dict[str, ReconciliationStatement] = {}
        self._statement_order: List[str] = []

    def record_metering(
        self,
        session_id: str,
        domain: MeteringDomain,
        operation_name: str,
        resource_units: float,
        cost_breakdown: ThreeDimensionalCost,
        billable: bool = True,
        policy_note: str = "",
        custom_record_id: Optional[str] = None,
    ) -> DomainMeteringRecord:
        """Append a bounded itemized record to the session ledger."""
        with self._lock:
            record_id = custom_record_id or f"ddm-{uuid.uuid4().hex[:10]}"
            now_ms = int(time.time() * 1000)

            rec = DomainMeteringRecord(
                record_id=record_id,
                session_id=session_id,
                domain=domain,
                operation_name=operation_name,
                resource_units=resource_units,
                cost_breakdown=cost_breakdown,
                billable=billable,
                policy_note=policy_note,
                timestamp_ms=now_ms,
            )
            self._records_by_session[session_id].append(rec)
            return rec

    def get_session_summary(self, session_id: str) -> SessionDualDomainSummary:
        """Compute aggregated 3D cost and domain split ratios for a session."""
        with self._lock:
            records = self._records_by_session.get(session_id, [])
            gw_token_cost = 0.0
            sb_compute_cost = 0.0
            tp_tool_cost = 0.0
            gw_ops = 0
            sb_ops = 0

            for r in records:
                if not r.billable:
                    continue
                gw_token_cost += r.cost_breakdown.model_token_cost_usd
                sb_compute_cost += r.cost_breakdown.sandbox_compute_cost_usd
                tp_tool_cost += r.cost_breakdown.thirdparty_tool_cost_usd

                if r.domain == MeteringDomain.GATEWAY_DOMAIN:
                    gw_ops += 1
                else:
                    sb_ops += 1

            total_cost = round(gw_token_cost + sb_compute_cost + tp_tool_cost, 6)
            total_ops = len(records)

            gw_ratio = round(gw_token_cost / total_cost, 4) if total_cost > 0 else 0.5
            sb_ratio = round((sb_compute_cost + tp_tool_cost) / total_cost, 4) if total_cost > 0 else 0.5

            now_ms = int(time.time() * 1000)
            return SessionDualDomainSummary(
                session_id=session_id,
                gateway_token_cost_usd=round(gw_token_cost, 6),
                sandbox_compute_cost_usd=round(sb_compute_cost, 6),
                thirdparty_tool_cost_usd=round(tp_tool_cost, 6),
                total_cost_usd=total_cost,
                total_operations=total_ops,
                gateway_ops_count=gw_ops,
                sandbox_ops_count=sb_ops,
                gateway_cost_ratio=gw_ratio,
                sandbox_cost_ratio=sb_ratio,
                generated_at_ms=now_ms,
            )

    def generate_reconciliation_statement(self, session_id: str) -> ReconciliationStatement:
        """Generate a cryptographically sealed financial audit statement for the session."""
        with self._lock:
            records = list(self._records_by_session.get(session_id, []))
            summary = self._compute_summary_unlocked(session_id, records)
            statement_id = f"recon-{session_id}-{int(time.time())}"
            sha256_hash = ReconciliationStatement.compute_sha256(session_id, summary, records)
            now_ms = int(time.time() * 1000)

            statement = ReconciliationStatement(
                statement_id=statement_id,
                session_id=session_id,
                summary=summary,
                records=records,
                integrity_sha256=sha256_hash,
                generated_at_ms=now_ms,
            )

            self._statements[statement_id] = statement
            self._statement_order.append(statement_id)
            return statement

    def _compute_summary_unlocked(self, session_id: str, records: List[DomainMeteringRecord]) -> SessionDualDomainSummary:
        gw_token_cost = 0.0
        sb_compute_cost = 0.0
        tp_tool_cost = 0.0
        gw_ops = 0
        sb_ops = 0

        for r in records:
            if not r.billable:
                continue
            gw_token_cost += r.cost_breakdown.model_token_cost_usd
            sb_compute_cost += r.cost_breakdown.sandbox_compute_cost_usd
            tp_tool_cost += r.cost_breakdown.thirdparty_tool_cost_usd

            if r.domain == MeteringDomain.GATEWAY_DOMAIN:
                gw_ops += 1
            else:
                sb_ops += 1

        total_cost = round(gw_token_cost + sb_compute_cost + tp_tool_cost, 6)
        total_ops = len(records)
        gw_ratio = round(gw_token_cost / total_cost, 4) if total_cost > 0 else 0.5
        sb_ratio = round((sb_compute_cost + tp_tool_cost) / total_cost, 4) if total_cost > 0 else 0.5
        now_ms = int(time.time() * 1000)

        return SessionDualDomainSummary(
            session_id=session_id,
            gateway_token_cost_usd=round(gw_token_cost, 6),
            sandbox_compute_cost_usd=round(sb_compute_cost, 6),
            thirdparty_tool_cost_usd=round(tp_tool_cost, 6),
            total_cost_usd=total_cost,
            total_operations=total_ops,
            gateway_ops_count=gw_ops,
            sandbox_ops_count=sb_ops,
            gateway_cost_ratio=gw_ratio,
            sandbox_cost_ratio=sb_ratio,
            generated_at_ms=now_ms,
        )

    def list_statements(self, limit: int = 50) -> List[ReconciliationStatement]:
        """List stored reconciliation statements, newest first."""
        with self._lock:
            results: List[ReconciliationStatement] = []
            for stmt_id in reversed(self._statement_order):
                item = self._statements.get(stmt_id)
                if item:
                    results.append(item)
                if len(results) >= limit:
                    break
            return results

    def reset(self) -> None:
        """Clear all session records and generated statements."""
        with self._lock:
            self._records_by_session.clear()
            self._statements.clear()
            self._statement_order.clear()


_DEFAULT_LEDGER: Optional[DualDomainMeteringLedger] = None
_INIT_LOCK = threading.Lock()


def get_default_dual_domain_ledger() -> DualDomainMeteringLedger:
    """Retrieve global thread-safe default DualDomainMeteringLedger instance."""
    global _DEFAULT_LEDGER
    if _DEFAULT_LEDGER is None:
        with _INIT_LOCK:
            if _DEFAULT_LEDGER is None:
                _DEFAULT_LEDGER = DualDomainMeteringLedger()
    return _DEFAULT_LEDGER
