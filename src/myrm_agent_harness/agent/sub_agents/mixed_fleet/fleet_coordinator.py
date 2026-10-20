"""myrm_agent_harness/agent/sub_agents/mixed_fleet/fleet_coordinator.py

[INPUT]
- threading
- datetime
- types

[OUTPUT]
- MixedFleetCoordinator

[POS]
myrm_agent_harness/agent/sub_agents/mixed_fleet/fleet_coordinator.py
"""

import threading
from datetime import UTC, datetime

from .types import (
    DispatchHandoffRequest,
    FleetExecutionStatusEnum,
    FleetNodeSpec,
    FleetRoleEnum,
    FleetStatusSnapshot,
    MixedFleetError,
    MixedFleetHandoffManifest,
    MixedFleetHandoffNotFoundError,
    MixedFleetOfflineError,
)


class MixedFleetCoordinator:
    """Thread-safe coordinator for Mixed Fleet Local Brain and Remote Executor orchestration."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fleets: dict[str, dict[FleetRoleEnum, FleetNodeSpec]] = {}
        self._manifests: dict[str, MixedFleetHandoffManifest] = {}
        self._chat_manifests: dict[str, list[str]] = {}

    def get_or_create_fleet(
        self, chat_id: str
    ) -> tuple[FleetNodeSpec, FleetNodeSpec]:
        """Ensure Local Brain and Remote Executor nodes exist for chat."""
        with self._lock:
            if chat_id not in self._fleets:
                now_iso = datetime.now(UTC).isoformat()
                local_brain = FleetNodeSpec(
                    node_id=f"node-local-{chat_id[:8]}",
                    role=FleetRoleEnum.LOCAL_BRAIN,
                    display_name="Local Brain (Privacy & Memory)",
                    is_online=True,
                    last_heartbeat=now_iso,
                    supported_capabilities=[
                        "local_memory",
                        "knowledge_base",
                        "privacy_gate",
                        "prompt_synthesis",
                    ],
                )
                remote_executor = FleetNodeSpec(
                    node_id=f"node-remote-{chat_id[:8]}",
                    role=FleetRoleEnum.REMOTE_EXECUTOR,
                    display_name="Remote Executor (24/7 Cloud Sandbox)",
                    is_online=True,
                    endpoint_url="https://remote-gateway.internal/executor",
                    last_heartbeat=now_iso,
                    supported_capabilities=[
                        "long_running_jobs",
                        "heavy_compilation",
                        "unattended_scraping",
                        "continuous_monitoring",
                    ],
                )
                self._fleets[chat_id] = {
                    FleetRoleEnum.LOCAL_BRAIN: local_brain,
                    FleetRoleEnum.REMOTE_EXECUTOR: remote_executor,
                }
                self._chat_manifests[chat_id] = []

            fleet = self._fleets[chat_id]
            return fleet[FleetRoleEnum.LOCAL_BRAIN], fleet[FleetRoleEnum.REMOTE_EXECUTOR]

    def dispatch_to_remote(
        self, request: DispatchHandoffRequest
    ) -> MixedFleetHandoffManifest:
        """Local Brain dispatches an asynchronous task package to Remote Executor."""
        if not request.task_instruction.strip():
            raise MixedFleetError("Task instruction cannot be empty.")

        with self._lock:
            local_node, remote_node = self.get_or_create_fleet(request.chat_id)

            if not remote_node.is_online:
                raise MixedFleetOfflineError(
                    f"Remote Executor node {remote_node.node_id} is currently offline."
                )

            now_iso = datetime.now(UTC).isoformat()

            # Compile structured markdown handoff artifact
            files_section = "\n".join(f"- `{f}`" for f in request.context_files) or "- None"
            handoff_md = (
                f"# Mixed Fleet Handoff Manifest\n\n"
                f"- **Manifest ID**: `{request.manifest_id}`\n"
                f"- **Chat ID**: `{request.chat_id}`\n"
                f"- **Dispatched At**: `{now_iso}`\n"
                f"- **Source Node**: `{local_node.display_name}` ({local_node.node_id})\n"
                f"- **Target Node**: `{remote_node.display_name}` ({remote_node.node_id})\n\n"
                f"## 1. Task Objective\n{request.task_instruction}\n\n"
                f"## 2. Injected Context Files\n{files_section}\n\n"
                f"## 3. Execution Contract\n"
                f"Remote Executor runs 24/7 in isolated sandbox. Output artifacts will be synced back to Local Brain."
            )

            manifest = MixedFleetHandoffManifest(
                manifest_id=request.manifest_id,
                chat_id=request.chat_id,
                source_role=FleetRoleEnum.LOCAL_BRAIN,
                target_role=FleetRoleEnum.REMOTE_EXECUTOR,
                task_instruction=request.task_instruction,
                handoff_markdown=handoff_md,
                context_files=list(request.context_files),
                execution_status=FleetExecutionStatusEnum.DISPATCHED,
                created_at=now_iso,
            )

            self._manifests[manifest.manifest_id] = manifest
            self._chat_manifests[request.chat_id].append(manifest.manifest_id)
            return manifest

    def get_manifest(self, manifest_id: str) -> MixedFleetHandoffManifest:
        """Retrieve manifest or raise MixedFleetHandoffNotFoundError."""
        with self._lock:
            manifest = self._manifests.get(manifest_id)
            if not manifest:
                raise MixedFleetHandoffNotFoundError(
                    f"Handoff manifest {manifest_id} not found."
                )
            return manifest

    def sync_from_remote(
        self, chat_id: str, manifest_id: str
    ) -> MixedFleetHandoffManifest:
        """Local Brain pulls the latest progress or result from Remote Executor."""
        with self._lock:
            manifest = self.get_manifest(manifest_id)
            if manifest.chat_id != chat_id:
                raise MixedFleetError(
                    f"Manifest {manifest_id} does not belong to chat {chat_id}"
                )

            manifest.synced_at = datetime.now(UTC).isoformat()
            return manifest

    def complete_remote_execution(
        self, manifest_id: str, output_summary: str
    ) -> MixedFleetHandoffManifest:
        """Mark remote execution as completed with output artifact summary."""
        with self._lock:
            manifest = self.get_manifest(manifest_id)
            manifest.execution_status = FleetExecutionStatusEnum.COMPLETED
            manifest.output_summary = output_summary
            manifest.synced_at = datetime.now(UTC).isoformat()
            return manifest

    def fail_remote_execution(
        self, manifest_id: str, error_detail: str
    ) -> MixedFleetHandoffManifest:
        """Mark remote execution as failed with diagnostic error details."""
        with self._lock:
            manifest = self.get_manifest(manifest_id)
            manifest.execution_status = FleetExecutionStatusEnum.FAILED
            manifest.error_detail = error_detail
            manifest.synced_at = datetime.now(UTC).isoformat()
            return manifest

    def update_heartbeat(
        self,
        chat_id: str,
        role: FleetRoleEnum,
        is_online: bool = True,
    ) -> FleetNodeSpec:
        """Update node heartbeat and availability."""
        with self._lock:
            self.get_or_create_fleet(chat_id)
            node = self._fleets[chat_id][role]
            node.is_online = is_online
            node.last_heartbeat = datetime.now(UTC).isoformat()
            return node

    def get_fleet_snapshot(self, chat_id: str) -> FleetStatusSnapshot:
        """Snapshot current fleet nodes and most recent handoff manifest."""
        with self._lock:
            local_node, remote_node = self.get_or_create_fleet(chat_id)
            manifest_ids = self._chat_manifests.get(chat_id, [])
            active_manifest: MixedFleetHandoffManifest | None = None
            if manifest_ids:
                active_manifest = self._manifests.get(manifest_ids[-1])

            return FleetStatusSnapshot(
                chat_id=chat_id,
                local_brain=local_node,
                remote_executor=remote_node,
                active_manifest=active_manifest,
                total_handoffs=len(manifest_ids),
            )
