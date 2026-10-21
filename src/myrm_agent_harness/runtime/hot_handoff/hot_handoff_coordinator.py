"""Local-to-cloud hot handoff coordinator and two-way task relay pipeline.

Coordinates task state freezing on local desktop, cryptographic input consistency
verification in the remote sandbox, offline cloud execution, and seamless reverse recall.

[OUTPUT]
- HotHandoffCoordinator: Orchestrates bidirectional task handoffs and material validation.

[INPUT]
- __future__
- time
- uuid
- collections
- pathlib

[OUTPUT]
- HotHandoffCoordinator

[POS]
Local-to-cloud hot handoff coordinator and two-way task relay pipeline.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from myrm_agent_harness.runtime.hot_handoff.handoff_types import (
    ExecutionEnvironment,
    HandoffPayload,
    HandoffPhase,
    HandoffReceipt,
    MaterialDigest,
)
from myrm_agent_harness.runtime.hot_handoff.material_integrity_guard import (
    MaterialIntegrityGuard,
)
from myrm_agent_harness.runtime.hot_handoff.workspace_syncer import (
    WorkspaceDeltaSyncer,
)


class HotHandoffCoordinator:
    """Manages the end-to-end task evacuation from local desktop to cloud sandboxes and back."""

    def __init__(self) -> None:
        self.syncer: WorkspaceDeltaSyncer = WorkspaceDeltaSyncer()
        self.integrity_guard: MaterialIntegrityGuard = MaterialIntegrityGuard()

    def evacuate_to_cloud(
        self,
        *,
        task_id: str,
        session_id: str,
        current_step: int,
        state_vector: dict[str, str | int | float | bool],
        local_workspace: Path | str,
        critical_materials: Iterable[Path | str] = (),
    ) -> tuple[HandoffPayload, bytes]:
        """Freeze local task execution and bundle state and workspace delta for cloud relay."""
        loc_root = Path(local_workspace).resolve()
        handoff_id = f"hoff_{uuid.uuid4().hex[:12]}"

        # 1. Compute cryptographic digests for critical input materials
        material_digests: list[MaterialDigest] = []
        for mat in critical_materials:
            mat_path = Path(mat).resolve()
            if mat_path.is_file():
                digest = self.integrity_guard.compute_file_digest(
                    mat_path,
                    relative_to=loc_root if mat_path.is_relative_to(loc_root) else None,
                )
                material_digests.append(digest)

        # 2. Package incremental files in workspace
        delta_manifest = self.syncer.compute_delta(loc_root)
        delta_bundle = self.syncer.export_delta_bundle(loc_root, delta_manifest)

        payload = HandoffPayload(
            handoff_id=handoff_id,
            task_id=task_id,
            session_id=session_id,
            origin_env=ExecutionEnvironment.LOCAL_DESKTOP,
            target_env=ExecutionEnvironment.CLOUD_SANDBOX,
            frozen_step_index=current_step,
            state_vector=dict(state_vector),
            materials=tuple(material_digests),
            delta_files=delta_manifest,
        )

        return payload, delta_bundle

    def receive_and_verify_cloud_handoff(
        self,
        payload: HandoffPayload,
        cloud_workspace: Path | str,
        delta_bundle: bytes | None = None,
    ) -> HandoffReceipt:
        """Apply delta bundle in the remote sandbox and verify input material integrity."""
        start_ts = time.perf_counter()
        c_root = Path(cloud_workspace).resolve()
        c_root.mkdir(parents=True, exist_ok=True)

        # 1. Apply workspace files if bundle was transferred
        transferred_bytes = len(delta_bundle) if delta_bundle else 0
        if delta_bundle:
            self.syncer.apply_delta_bundle(c_root, delta_bundle)

        # 2. Cryptographic input material verification
        if payload.materials:
            ok, errors = self.integrity_guard.batch_verify(payload.materials, c_root)
            if not ok:
                duration_ms = (time.perf_counter() - start_ts) * 1000.0
                return HandoffReceipt(
                    handoff_id=payload.handoff_id,
                    task_id=payload.task_id,
                    phase=HandoffPhase.FAILED,
                    is_success=False,
                    material_consistency_passed=False,
                    active_env=ExecutionEnvironment.LOCAL_DESKTOP,
                    error_message=f"Material verification failed: {'; '.join(errors)}",
                    transferred_bytes=transferred_bytes,
                    duration_ms=round(duration_ms, 2),
                )

        duration_ms = (time.perf_counter() - start_ts) * 1000.0
        return HandoffReceipt(
            handoff_id=payload.handoff_id,
            task_id=payload.task_id,
            phase=HandoffPhase.CLOUD_RUNNING,
            is_success=True,
            material_consistency_passed=True,
            active_env=ExecutionEnvironment.CLOUD_SANDBOX,
            transferred_bytes=transferred_bytes,
            duration_ms=round(duration_ms, 2),
        )

    def recall_to_local(
        self,
        *,
        handoff_id: str,
        task_id: str,
        cloud_workspace: Path | str,
        local_workspace: Path | str,
    ) -> HandoffReceipt:
        """Synchronize completed cloud sandbox artifacts back to the local user workspace."""
        start_ts = time.perf_counter()
        c_root = Path(cloud_workspace).resolve()
        l_root = Path(local_workspace).resolve()

        # Delta sync from cloud back to local
        local_manifest = self.syncer.scan_files(l_root)
        delta_manifest = self.syncer.compute_delta(c_root, target_manifest=local_manifest)
        bundle = self.syncer.export_delta_bundle(c_root, delta_manifest)
        _, bytes_written = self.syncer.apply_delta_bundle(l_root, bundle)

        duration_ms = (time.perf_counter() - start_ts) * 1000.0
        return HandoffReceipt(
            handoff_id=handoff_id,
            task_id=task_id,
            phase=HandoffPhase.COMPLETED,
            is_success=True,
            material_consistency_passed=True,
            active_env=ExecutionEnvironment.LOCAL_DESKTOP,
            transferred_bytes=bytes_written,
            duration_ms=round(duration_ms, 2),
        )
