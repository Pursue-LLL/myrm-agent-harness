"""Four-Zone Workspace Topology and scaffolding generator.

[INPUT]
- root_dir: Target directory path for workspace scaffolding

[OUTPUT]
- FourZoneScaffold: Generates standard 4-zone directory topology and resolves paths to zones

[POS]
Harness core security scaffold. Sets up physical isolation zones separating raw input,
intermediate drafts, shared factual blueprints, and client-facing deliverables.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from myrm_agent_harness.core.security.four_zone.types import WorkspaceZone

logger = logging.getLogger(__name__)

_ZONE_METADATA: dict[WorkspaceZone, dict[str, str | bool]] = {
    WorkspaceZone.ZONE_01_RAW: {
        "zone": WorkspaceZone.ZONE_01_RAW.value,
        "description": "原始材料区：外部输入与客户原件，物理只读保护，严禁修改/删除/覆盖",
        "read_only": True,
        "writable": False,
    },
    WorkspaceZone.ZONE_02_DRAFT: {
        "zone": WorkspaceZone.ZONE_02_DRAFT.value,
        "description": "过程草稿区：中间分析、草案试错与处理废稿，随意实验不污染底稿",
        "read_only": False,
        "writable": True,
    },
    WorkspaceZone.ZONE_03_CANONICAL: {
        "zone": WorkspaceZone.ZONE_03_CANONICAL.value,
        "description": "内容底稿区：拍板确认的事实源与蓝图，所有交付物必须以此为准",
        "read_only": False,
        "writable": True,
    },
    WorkspaceZone.ZONE_04_DELIVERABLE: {
        "zone": WorkspaceZone.ZONE_04_DELIVERABLE.value,
        "description": "交付成果区：最终交付物与客户成品，严禁存放未经底稿确认的草稿",
        "read_only": False,
        "writable": True,
    },
}


class FourZoneScaffold:
    """Manages creation and topology detection of four-zone workspaces."""

    @classmethod
    def initialize_workspace(cls, root_dir: str) -> dict[str, str]:
        """Create the 4 standard zones under root_dir with metadata manifests."""
        created_paths: dict[str, str] = {}
        root = Path(root_dir)
        root.mkdir(parents=True, exist_ok=True)

        for zone, meta in _ZONE_METADATA.items():
            zone_dir = root / zone.value
            zone_dir.mkdir(parents=True, exist_ok=True)

            meta_file = zone_dir / ".zone_meta.json"
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            readme_file = zone_dir / "README.md"
            if not readme_file.exists():
                readme_file.write_text(
                    f"# {meta['zone']}\n\n{meta['description']}\n",
                    encoding="utf-8",
                )

            created_paths[zone.value] = str(zone_dir)

        logger.info("Initialized Four-Zone Workspace at: %s", root_dir)
        return created_paths

    @classmethod
    def detect_zone(cls, file_path: str) -> WorkspaceZone | None:
        """Determine which workspace zone a given path belongs to."""
        normalized = file_path.replace("\\", "/")
        parts = normalized.split("/")

        for zone in WorkspaceZone:
            if zone.value in parts:
                return zone

        return None
