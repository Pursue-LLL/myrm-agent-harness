"""Unit tests for Four-Zone Workspace Layout and Read-Only Source Protection.

[POS]
Verifies 4-zone directory topology initialization, zone detection, absolute read-only
protection of Zone 01 raw original materials, and one-way deliverable promotion.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.four_zone import (
    FourZoneProtectionGuard,
    FourZoneScaffold,
    OneWayPromotionPipeline,
    ReadOnlySourceZoneViolationError,
    WorkspaceZone,
    ZoneOperationType,
)


def test_four_zone_scaffold_initialization_and_detection(tmp_path: Path) -> None:
    workspace_root = str(tmp_path / "project_workspace")
    created = FourZoneScaffold.initialize_workspace(workspace_root)

    # All four zones must be initialized
    assert len(created) == 4
    for zone in WorkspaceZone:
        assert zone.value in created
        zone_dir = Path(created[zone.value])
        assert zone_dir.is_dir()
        assert (zone_dir / ".zone_meta.json").is_file()
        assert (zone_dir / "README.md").is_file()

    # Zone detection
    raw_file = os.path.join(workspace_root, WorkspaceZone.ZONE_01_RAW.value, "contract_v1.pdf")
    draft_file = os.path.join(workspace_root, WorkspaceZone.ZONE_02_DRAFT.value, "analysis.md")
    canonical_file = os.path.join(workspace_root, WorkspaceZone.ZONE_03_CANONICAL.value, "spec.json")
    deliverable_file = os.path.join(workspace_root, WorkspaceZone.ZONE_04_DELIVERABLE.value, "final.docx")

    assert FourZoneScaffold.detect_zone(raw_file) == WorkspaceZone.ZONE_01_RAW
    assert FourZoneScaffold.detect_zone(draft_file) == WorkspaceZone.ZONE_02_DRAFT
    assert FourZoneScaffold.detect_zone(canonical_file) == WorkspaceZone.ZONE_03_CANONICAL
    assert FourZoneScaffold.detect_zone(deliverable_file) == WorkspaceZone.ZONE_04_DELIVERABLE
    assert FourZoneScaffold.detect_zone("/outside/workspace/other.txt") is None


def test_four_zone_guard_read_only_invariants(tmp_path: Path) -> None:
    workspace_root = str(tmp_path / "project_workspace")
    FourZoneScaffold.initialize_workspace(workspace_root)

    raw_path = os.path.join(workspace_root, WorkspaceZone.ZONE_01_RAW.value, "original_dataset.csv")

    # 1. READ is permitted on Zone 01
    read_res = FourZoneProtectionGuard.assert_operation_allowed(raw_path, ZoneOperationType.READ)
    assert read_res.allowed is True
    assert read_res.zone == WorkspaceZone.ZONE_01_RAW

    # 2. WRITE on Zone 01 raises ReadOnlySourceZoneViolationError
    with pytest.raises(ReadOnlySourceZoneViolationError) as exc_write:
        FourZoneProtectionGuard.assert_operation_allowed(raw_path, ZoneOperationType.WRITE)
    assert "strictly READ-ONLY" in str(exc_write.value)

    # 3. DELETE and RENAME on Zone 01 raise ReadOnlySourceZoneViolationError
    with pytest.raises(ReadOnlySourceZoneViolationError):
        FourZoneProtectionGuard.assert_operation_allowed(raw_path, ZoneOperationType.DELETE)
    with pytest.raises(ReadOnlySourceZoneViolationError):
        FourZoneProtectionGuard.assert_operation_allowed(raw_path, ZoneOperationType.RENAME)

    # 4. Other zones permit WRITE
    draft_path = os.path.join(workspace_root, WorkspaceZone.ZONE_02_DRAFT.value, "notes.md")
    draft_res = FourZoneProtectionGuard.assert_operation_allowed(draft_path, ZoneOperationType.WRITE)
    assert draft_res.allowed is True


def test_replicate_to_draft_and_one_way_promotion(tmp_path: Path) -> None:
    workspace_root = str(tmp_path / "project_workspace")
    FourZoneScaffold.initialize_workspace(workspace_root)

    # 1. Put original client document into Zone 01
    raw_dir = Path(workspace_root) / WorkspaceZone.ZONE_01_RAW.value
    (raw_dir / "customer_brief.txt").write_text("Original customer requirements", encoding="utf-8")

    # 2. Replicate to Zone 02 draft
    draft_full = FourZoneProtectionGuard.replicate_to_draft(
        root_dir=workspace_root,
        source_rel_path="customer_brief.txt",
        draft_rel_path="working_draft.txt",
    )
    assert os.path.isfile(draft_full)
    assert Path(draft_full).read_text(encoding="utf-8") == "Original customer requirements"

    # Modify draft in Zone 02
    Path(draft_full).write_text("Refined analysis in draft", encoding="utf-8")

    # 3. Promote draft to canonical (Zone 02 -> Zone 03)
    p1 = OneWayPromotionPipeline.promote_draft_to_canonical(
        root_dir=workspace_root,
        draft_rel_path="working_draft.txt",
        canonical_rel_path="approved_blueprint.txt",
        reviewer_id="lead_architect",
    )
    assert p1.source_zone == WorkspaceZone.ZONE_02_DRAFT
    assert p1.target_zone == WorkspaceZone.ZONE_03_CANONICAL
    assert Path(p1.target_path).read_text(encoding="utf-8") == "Refined analysis in draft"

    # 4. Promote canonical to deliverable (Zone 03 -> Zone 04)
    p2 = OneWayPromotionPipeline.promote_canonical_to_deliverable(
        root_dir=workspace_root,
        canonical_rel_path="approved_blueprint.txt",
        deliverable_rel_path="final_deliverable.txt",
        reviewer_id="project_manager",
    )
    assert p2.source_zone == WorkspaceZone.ZONE_03_CANONICAL
    assert p2.target_zone == WorkspaceZone.ZONE_04_DELIVERABLE
    assert Path(p2.target_path).read_text(encoding="utf-8") == "Refined analysis in draft"
