"""Context bundle facade.

[INPUT]
- toolkits.storage.base::StorageProvider (POS: storage provider abstract base class)
- toolkits.storage.local::LocalStorageBackend (POS: local storage backend implementation)
- .hooks::ContextLifecycleHooks (POS: context lifecycle hook registration)
- .index::ContextIndexRegistry (POS: context index registration protocol)
- .spec::ContextBundleSpec, ContextScene (POS: context bundle specification types)
- .volume::VolumeLayout (POS: context bundle volume layout)

[OUTPUT]
- ContextBundleHealth: non-content health snapshot
- ContextBundleFacade: unified entry for memory/storage/offload/index/hooks paths

[POS]
Thin facade over existing Harness storage and volume paths. Does not create MemoryManager or
import agent/ runtime modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.storage.base import StorageProvider
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend

from .hooks import ContextLifecycleHooks
from .index import ContextIndexRegistry
from .spec import ContextBundleSpec, ContextScene
from .volume import VolumeLayout


@dataclass(frozen=True, slots=True)
class ContextBundleHealth:
    bundle_id: str
    schema_version: int
    volume_layout_version: int
    state_dir: str
    writable: bool
    manifest_exists: bool
    scene_paths: dict[str, str]
    index_status: dict[str, str]


class ContextBundleFacade:
    """Unified context volume facade for memory, workspace, offload, and archive scenes."""

    def __init__(
        self,
        *,
        volume: VolumeLayout,
        spec: ContextBundleSpec,
        index_registry: ContextIndexRegistry | None = None,
        lifecycle_hooks: ContextLifecycleHooks | None = None,
        storage_backend: StorageProvider | None = None,
    ) -> None:
        self._volume = volume
        self._spec = spec
        self._index = index_registry or ContextIndexRegistry()
        self._hooks = lifecycle_hooks or ContextLifecycleHooks()
        self._storage = storage_backend

    @classmethod
    def from_state_dir(
        cls,
        state_dir: str | Path,
        *,
        spec: ContextBundleSpec | None = None,
        ensure_layout: bool = True,
    ) -> ContextBundleFacade:
        bundle_spec = spec or ContextBundleSpec()
        volume = VolumeLayout.from_state_dir(state_dir)
        if ensure_layout:
            volume.ensure_directories()
        storage = LocalStorageBackend(str(volume.harness_path))
        return cls(volume=volume, spec=bundle_spec, storage_backend=storage)

    @property
    def spec(self) -> ContextBundleSpec:
        return self._spec

    @property
    def volume(self) -> VolumeLayout:
        return self._volume

    def memory_path(self) -> Path:
        return self._volume.memory_path

    def harness_path(self) -> Path:
        return self._volume.harness_path

    def qdrant_path(self) -> Path:
        return self._volume.qdrant_path

    def archive_path(self) -> Path:
        return self._volume.archive_path

    def offload_root(self) -> Path:
        return self._volume.offload_root

    def session_offload_dir(self, session_id: str) -> Path:
        return self._volume.session_offload_dir(session_id)

    def task_workspace_root(self) -> Path | None:
        overlay = self._spec.agent_overlay
        if overlay is None or not overlay.task_workspace_root:
            return None
        return Path(overlay.task_workspace_root).expanduser().resolve()

    def vault_dir(self, workspace_root: str | Path) -> Path:
        """Directory where agent ArtifactVault stores objects for a task workspace."""
        return Path(workspace_root).expanduser().resolve() / ".myrm" / "vault"

    def storage(self) -> StorageProvider:
        if self._storage is None:
            self._storage = LocalStorageBackend(str(self._volume.harness_path))
        return self._storage

    def index(self) -> ContextIndexRegistry:
        return self._index

    def hooks(self) -> ContextLifecycleHooks:
        return self._hooks

    def scene_path(self, scene: ContextScene) -> Path:
        if scene is ContextScene.MEMORY:
            return self._volume.memory_path
        if scene is ContextScene.WORKSPACE:
            task_root = self.task_workspace_root()
            return task_root if task_root is not None else self._volume.harness_path
        if scene is ContextScene.OFFLOAD:
            return self._volume.offload_root
        return self._volume.archive_path

    def allows_persistent_write(self, scene: ContextScene) -> bool:
        return self._spec.allows_persistent_write(scene)

    async def health(self) -> ContextBundleHealth:
        state_dir = self._volume.state_dir
        target = state_dir if state_dir.exists() else state_dir.parent
        writable = target.exists() and os.access(target, os.W_OK)
        index_status = await self._index.health_by_scene()
        scene_paths = {scene.value: str(self.scene_path(scene)) for scene in ContextScene}
        return ContextBundleHealth(
            bundle_id=self._spec.bundle_id,
            schema_version=self._spec.schema_version,
            volume_layout_version=self._spec.volume_layout_version,
            state_dir=str(state_dir),
            writable=writable,
            manifest_exists=self._volume.manifest_path().is_file(),
            scene_paths=scene_paths,
            index_status=index_status,
        )
