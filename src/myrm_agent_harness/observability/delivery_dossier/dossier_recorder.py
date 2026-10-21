"""
[INPUT]: Task specs, agent fingerprints, execution traces, test receipts, and acceptance reviews.
[OUTPUT]: Immutable DeliveryEvidenceDossier records with cryptographic SHA256 integrity checksums.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/delivery_dossier/dossier_recorder.py
"""

from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Dict, List, Optional

from .models import (
    AgentPersonaFingerprint,
    DeliveryEvidenceDossier,
    ExecutionMode,
    PhysicalVerificationReceipt,
    TaskSpecRecord,
    ToolExecutionTraceItem,
    UserAcceptanceStatus,
)


class DeliveryDossierRecorder:
    """
    Creates and manages immutable delivery evidence dossiers, ensuring 100% reproducible
    task verifications, test receipts, and acceptance conclusions across distributed agents.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dossiers: Dict[str, DeliveryEvidenceDossier] = {}
        self._task_index: Dict[str, str] = {}

    def create_dossier(
        self,
        task_id: str,
        execution_mode: ExecutionMode,
        spec: TaskSpecRecord,
        persona: AgentPersonaFingerprint,
        tool_traces: List[ToolExecutionTraceItem],
        verification: PhysicalVerificationReceipt,
        acceptance: UserAcceptanceStatus,
        total_tokens_consumed: int,
        wasted_friction_tokens: int,
        rework_count: int,
    ) -> DeliveryEvidenceDossier:
        now_iso = datetime.now(timezone.utc).isoformat()
        raw_seed = (
            f"{task_id}:{persona.agent_id}:{persona.model_name}:"
            f"{verification.artifact_sha256}:{acceptance.value}:{now_iso}"
        )
        dossier_id = f"dos_{hashlib.sha256(raw_seed.encode('utf-8')).hexdigest()[:16]}"

        # Compute tamper-evident checksum
        hasher = hashlib.sha256()
        hasher.update(dossier_id.encode("utf-8"))
        hasher.update(task_id.encode("utf-8"))
        hasher.update(spec.task_goal.encode("utf-8"))
        hasher.update(verification.artifact_sha256.encode("utf-8"))
        hasher.update(acceptance.value.encode("utf-8"))
        for trace in tool_traces:
            hasher.update(f"{trace.tool_name}:{trace.exit_code}".encode("utf-8"))
        checksum = hasher.hexdigest()

        dossier = DeliveryEvidenceDossier(
            dossier_id=dossier_id,
            task_id=task_id,
            execution_mode=execution_mode,
            spec=spec,
            persona=persona,
            tool_traces=tool_traces,
            verification=verification,
            acceptance=acceptance,
            total_tokens_consumed=total_tokens_consumed,
            wasted_friction_tokens=wasted_friction_tokens,
            rework_count=rework_count,
            dossier_checksum_sha256=checksum,
            created_at=now_iso,
        )

        with self._lock:
            self._dossiers[dossier_id] = dossier
            self._task_index[task_id] = dossier_id

        return dossier

    def get_dossier(self, dossier_id: str) -> Optional[DeliveryEvidenceDossier]:
        with self._lock:
            return self._dossiers.get(dossier_id)

    def get_dossier_by_task(self, task_id: str) -> Optional[DeliveryEvidenceDossier]:
        with self._lock:
            d_id = self._task_index.get(task_id)
            return self._dossiers.get(d_id) if d_id else None

    def export_json(self, dossier_id: str) -> Optional[str]:
        d = self.get_dossier(dossier_id)
        if not d:
            return None
        payload = {
            "dossier_id": d.dossier_id,
            "task_id": d.task_id,
            "execution_mode": d.execution_mode.value,
            "spec": {
                "task_goal": d.spec.task_goal,
                "acceptance_criteria": d.spec.acceptance_criteria,
                "non_goals": d.spec.non_goals,
            },
            "persona": {
                "agent_id": d.persona.agent_id,
                "model_name": d.persona.model_name,
                "prompt_hash": d.persona.prompt_hash,
                "mounted_skills": d.persona.mounted_skills,
            },
            "tool_traces": [
                {
                    "tool_name": t.tool_name,
                    "arguments_summary": t.arguments_summary,
                    "duration_ms": t.duration_ms,
                    "exit_code": t.exit_code,
                    "error_message": t.error_message,
                }
                for t in d.tool_traces
            ],
            "verification": {
                "test_suite_exit_code": d.verification.test_suite_exit_code,
                "passed_tests_count": d.verification.passed_tests_count,
                "failed_tests_count": d.verification.failed_tests_count,
                "artifact_path": d.verification.artifact_path,
                "artifact_sha256": d.verification.artifact_sha256,
                "verified_at": d.verification.verified_at,
            },
            "acceptance": d.acceptance.value,
            "total_tokens_consumed": d.total_tokens_consumed,
            "wasted_friction_tokens": d.wasted_friction_tokens,
            "rework_count": d.rework_count,
            "dossier_checksum_sha256": d.dossier_checksum_sha256,
            "created_at": d.created_at,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
