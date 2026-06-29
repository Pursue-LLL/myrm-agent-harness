"""Context bundle specification types.

[INPUT]
- enum::StrEnum (POS: Python string enumeration)
- dataclasses::dataclass (POS: Python dataclass)

[OUTPUT]
- ContextScene: active context scenes within a bundle
- IncognitoPolicy: ephemeral session write policy
- AgentContextOverlay: task workspace vs memory volume decoupling
- ContextBundleSpec: immutable bundle identity and layout contract

[POS]
Framework-level context bundle specification. Pure types with no Agent or Server imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

CONTEXT_BUNDLE_SCHEMA_VERSION = 1
VOLUME_LAYOUT_VERSION = 1

DEFAULT_BUNDLE_ID = "default"


class ContextScene(StrEnum):
    """Logical scenes mounted under a single ContextBundle volume."""

    MEMORY = "memory"
    WORKSPACE = "workspace"
    OFFLOAD = "offload"
    ARCHIVE = "archive"


DEFAULT_SCENES: tuple[ContextScene, ...] = (
    ContextScene.MEMORY,
    ContextScene.WORKSPACE,
    ContextScene.OFFLOAD,
    ContextScene.ARCHIVE,
)


@dataclass(frozen=True, slots=True)
class IncognitoPolicy:
    """Skip persistent writes for selected scenes during ephemeral sessions."""

    enabled: bool = False
    skip_scenes: frozenset[ContextScene] = field(
        default_factory=lambda: frozenset({ContextScene.MEMORY, ContextScene.ARCHIVE})
    )


@dataclass(frozen=True, slots=True)
class AgentContextOverlay:
    """Decouple task cwd from long-lived memory scenes (OpenClaw/LobsterAI pattern)."""

    task_workspace_root: str | None = None
    memory_scenes_pinned: bool = True


@dataclass(frozen=True, slots=True)
class ContextBundleSpec:
    """Immutable bundle contract shared by Harness volume layout and Server binding."""

    bundle_id: str = DEFAULT_BUNDLE_ID
    schema_version: int = CONTEXT_BUNDLE_SCHEMA_VERSION
    volume_layout_version: int = VOLUME_LAYOUT_VERSION
    scenes: tuple[ContextScene, ...] = DEFAULT_SCENES
    incognito: IncognitoPolicy | None = None
    agent_overlay: AgentContextOverlay | None = None

    def active_scene_values(self) -> tuple[str, ...]:
        return tuple(scene.value for scene in self.scenes)

    def allows_persistent_write(self, scene: ContextScene) -> bool:
        if self.incognito is None or not self.incognito.enabled:
            return True
        return scene not in self.incognito.skip_scenes
