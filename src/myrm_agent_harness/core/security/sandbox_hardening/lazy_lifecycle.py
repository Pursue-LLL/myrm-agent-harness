"""Lazy provisioning and disposable lifecycle manager for hardened sandboxes."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from .eight_flag_builder import EightFlagBuilder
from .types import (
    EightFlagSandboxConfig,
    HardenedDockerCommand,
    ProvisionStatus,
)

logger = logging.getLogger(__name__)


class LazySandboxLifecycleManager:
    """Manages lazy container provisioning and disposable cleanup cycles."""

    def __init__(
        self,
        config: EightFlagSandboxConfig | None = None,
        builder: EightFlagBuilder | None = None,
    ) -> None:
        self.config = config or EightFlagSandboxConfig()
        self.builder = builder or EightFlagBuilder(self.config)
        self._lock = threading.Lock()
        self._status: ProvisionStatus = ProvisionStatus.UNINITIALIZED
        self._container_id: str | None = None
        self._provision_timestamp: float | None = None
        self._command_spec: HardenedDockerCommand | None = None

    @property
    def status(self) -> ProvisionStatus:
        """Current lifecycle status."""
        with self._lock:
            return self._status

    @property
    def container_id(self) -> str | None:
        """Active container identifier, if provisioned."""
        with self._lock:
            return self._container_id

    def ensure_provisioned(
        self,
        image: str = "ghcr.io/myrm-ai/sandbox-runtime:latest",
        extra_mounts: list[str] | None = None,
    ) -> HardenedDockerCommand:
        """Lazily provision the container on-demand when first code execution is requested."""
        with self._lock:
            if self._status == ProvisionStatus.RUNNING and self._command_spec is not None:
                return self._command_spec

            cmd = self.builder.build_run_args(
                image=image,
                extra_mounts=extra_mounts,
            )
            self._command_spec = cmd
            self._status = ProvisionStatus.RUNNING
            self._container_id = f"cntr-{int(datetime.now(UTC).timestamp())}"
            self._provision_timestamp = datetime.now(UTC).timestamp()
            logger.info(
                "Hardened sandbox dynamically provisioned: container_id=%s verified=%s",
                self._container_id,
                cmd.flags_verified,
            )
            return cmd

    def dispose(self) -> None:
        """Tear down and dispose of the sandbox, restoring clean state."""
        with self._lock:
            if self._status == ProvisionStatus.DISPOSED:
                return
            logger.info("Disposing sandbox container: container_id=%s", self._container_id)
            self._status = ProvisionStatus.DISPOSED
            self._container_id = None
            self._command_spec = None
            self._provision_timestamp = None

    def reset(self) -> None:
        """Reset lifecycle to uninitialized state for next cycle."""
        with self._lock:
            self._status = ProvisionStatus.UNINITIALIZED
            self._container_id = None
            self._command_spec = None
            self._provision_timestamp = None
