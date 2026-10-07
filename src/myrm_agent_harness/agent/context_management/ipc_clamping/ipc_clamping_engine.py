"""IPC Message Clamping and Large Artifact Spillover Engine (Item 216).

[INPUT]
- sender_id, receiver_id, message: Inter-agent IPC transmission parameters.
- IpcClampingConfig: Config controlling length limits, preview sizes, and spill paths.

[OUTPUT]
- IpcClampingOutcome: Evaluation outcome with rewritten summary payload and artifact reference.
- Stored raw artifact payloads accessible for downstream on-demand file reading.

[POS]
- Clamps bloated inter-agent communications and automatically offloads large texts
- to sandbox volume files, protecting downstream agent context windows from exploding.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from .ipc_clamping_types import (
    IpcClampingAction,
    IpcClampingConfig,
    IpcClampingOutcome,
    SpilloverArtifactSpec,
)


class IpcMessageClampingAndSpilloverEngine:
    """Gateway orchestrating inter-agent message clamping and artifact spillover offloading."""

    def __init__(self, config: IpcClampingConfig | None = None) -> None:
        self._config = config or IpcClampingConfig()
        # artifact_id/artifact_path -> raw text content
        self._artifacts: dict[str, str] = {}
        # artifact_id -> SpilloverArtifactSpec
        self._artifact_specs: dict[str, SpilloverArtifactSpec] = {}

    @property
    def config(self) -> IpcClampingConfig:
        """Returns current engine configuration."""
        return self._config

    def process_inter_agent_message(
        self,
        sender_id: str,
        receiver_id: str,
        message: str,
    ) -> IpcClampingOutcome:
        """Evaluates an inter-agent message, passing it through or spilling over if oversized."""
        start_time = time.perf_counter()
        original_len = len(message)

        # 1. Passthrough check
        if not self._config.enabled or original_len <= self._config.max_clamped_chars:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return IpcClampingOutcome(
                action=IpcClampingAction.PASSTHROUGH,
                sender_agent_id=sender_id,
                receiver_agent_id=receiver_id,
                effective_message=message,
                original_char_count=original_len,
                effective_char_count=original_len,
                spillover_artifact=None,
                duration_ms=duration_ms,
            )

        # 2. Oversize handling without auto-spillover
        if not self._config.auto_spillover:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = (
                f"[IPC ERROR: Message from {sender_id} rejected. Payload size "
                f"{original_len} exceeds clamping limit {self._config.max_clamped_chars}.]"
            )
            return IpcClampingOutcome(
                action=IpcClampingAction.REJECTED_OVERSIZE,
                sender_agent_id=sender_id,
                receiver_agent_id=receiver_id,
                effective_message=err_msg,
                original_char_count=original_len,
                effective_char_count=len(err_msg),
                spillover_artifact=None,
                duration_ms=duration_ms,
            )

        # 3. Offload to artifact spillover
        artifact_id = f"spill_{uuid.uuid4().hex[:12]}"
        artifact_path = f"{self._config.artifact_storage_prefix.rstrip('/')}/{artifact_id}.md"
        sha256_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

        # Generate head summary preview
        preview_len = self._config.summary_preview_chars
        preview_text = message[:preview_len].strip()
        if len(message) > preview_len:
            preview_text += "..."

        spec = SpilloverArtifactSpec(
            artifact_id=artifact_id,
            sender_agent_id=sender_id,
            receiver_agent_id=receiver_id,
            artifact_path=artifact_path,
            sha256=sha256_hash,
            original_char_count=original_len,
            summary=preview_text,
            created_at=time.time(),
        )

        # Persist payload into in-memory store
        self._artifacts[artifact_id] = message
        self._artifacts[artifact_path] = message
        self._artifact_specs[artifact_id] = spec

        # Construct rewritten lean payload
        rewritten_payload = (
            f"[LARGE IPC PAYLOAD DETECTED & SPILLED: {original_len:,} characters]\n"
            f"Content Digest (SHA-256): {sha256_hash}\n"
            f"Summary Preview:\n"
            f'"""\n{preview_text}\n"""\n\n'
            f"Full raw data safely offloaded to sandbox artifact: file://{artifact_path}\n"
            f"Instructions: Use 'read_file' tool with target path '{artifact_path}' "
            f"if deep detailed inspection is required."
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return IpcClampingOutcome(
            action=IpcClampingAction.SPILLOVER_REPLACED,
            sender_agent_id=sender_id,
            receiver_agent_id=receiver_id,
            effective_message=rewritten_payload,
            original_char_count=original_len,
            effective_char_count=len(rewritten_payload),
            spillover_artifact=spec,
            duration_ms=duration_ms,
        )

    def get_spillover_payload(self, artifact_path_or_id: str) -> str | None:
        """Retrieves raw content of an offloaded artifact by ID or path."""
        return self._artifacts.get(artifact_path_or_id)

    def get_artifact_spec(self, artifact_id: str) -> SpilloverArtifactSpec | None:
        """Retrieves metadata specification of an offloaded artifact."""
        return self._artifact_specs.get(artifact_id)

    def clear(self) -> None:
        """Clears all stored artifacts and specifications."""
        self._artifacts.clear()
        self._artifact_specs.clear()
