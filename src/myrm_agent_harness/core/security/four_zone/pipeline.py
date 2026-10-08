"""One-way artifact promotion pipeline across four workspace zones.

[INPUT]
- root_dir, source and target relative paths, reviewer ID

[OUTPUT]
- OneWayPromotionPipeline: Enforces strict sequential advancement of deliverables
- promote_draft_to_canonical, promote_canonical_to_deliverable

[POS]
Harness core security pipeline. Guarantees that deliverables in Zone 04 are produced
strictly from ratified facts in Zone 03, eliminating stale draft hallucination in final delivery.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.core.security.four_zone.types import (
    WorkspaceZone,
    ZonePromotionRecord,
)

logger = logging.getLogger(__name__)


class OneWayPromotionPipeline:
    """Controls the forward lifecycle promotion of artifacts across workspace zones."""

    @classmethod
    def promote_draft_to_canonical(
        cls,
        root_dir: str,
        draft_rel_path: str,
        canonical_rel_path: str,
        reviewer_id: str,
    ) -> ZonePromotionRecord:
        """Promote an approved draft from Zone 02 to Zone 03 as the shared single source of truth."""
        root = Path(root_dir)
        src = root / WorkspaceZone.ZONE_02_DRAFT.value / draft_rel_path
        dst = root / WorkspaceZone.ZONE_03_CANONICAL.value / canonical_rel_path

        if not src.exists():
            raise FileNotFoundError(f"Draft file not found in Zone 02: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        record = ZonePromotionRecord(
            promotion_id=f"prom_{uuid4().hex[:12]}",
            source_zone=WorkspaceZone.ZONE_02_DRAFT,
            target_zone=WorkspaceZone.ZONE_03_CANONICAL,
            source_path=str(src),
            target_path=str(dst),
            promoted_by=reviewer_id,
        )
        logger.info("Promoted draft to canonical source of truth: %s -> %s", src, dst)
        return record

    @classmethod
    def promote_canonical_to_deliverable(
        cls,
        root_dir: str,
        canonical_rel_path: str,
        deliverable_rel_path: str,
        reviewer_id: str,
    ) -> ZonePromotionRecord:
        """Promote a finalized artifact from Zone 03 to Zone 04 as the customer deliverable."""
        root = Path(root_dir)
        src = root / WorkspaceZone.ZONE_03_CANONICAL.value / canonical_rel_path
        dst = root / WorkspaceZone.ZONE_04_DELIVERABLE.value / deliverable_rel_path

        if not src.exists():
            raise FileNotFoundError(f"Canonical source not found in Zone 03: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        record = ZonePromotionRecord(
            promotion_id=f"prom_{uuid4().hex[:12]}",
            source_zone=WorkspaceZone.ZONE_03_CANONICAL,
            target_zone=WorkspaceZone.ZONE_04_DELIVERABLE,
            source_path=str(src),
            target_path=str(dst),
            promoted_by=reviewer_id,
        )
        logger.info("Promoted canonical artifact to final deliverable: %s -> %s", src, dst)
        return record
