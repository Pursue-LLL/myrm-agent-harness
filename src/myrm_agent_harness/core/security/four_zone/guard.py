"""Protection guard enforcing absolute read-only invariants on Zone 01 original assets.

[INPUT]
- file_path, operation (read, write, delete, rename, promote)

[OUTPUT]
- FourZoneProtectionGuard: Validates file operations against zone rules
- assert_operation_allowed, replicate_to_draft

[POS]
Harness core security guard. Intercepts file operations targeting `01_原始材料/`,
raising ReadOnlySourceZoneViolationError on any write/delete/rename attempt.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from myrm_agent_harness.core.security.four_zone.scaffold import FourZoneScaffold
from myrm_agent_harness.core.security.four_zone.types import (
    ReadOnlySourceZoneViolationError,
    WorkspaceZone,
    ZoneOperationType,
    ZoneValidationResult,
)

logger = logging.getLogger(__name__)


class FourZoneProtectionGuard:
    """Enforces read-only access on customer raw originals in Zone 01."""

    @classmethod
    def assert_operation_allowed(
        cls,
        file_path: str,
        operation: ZoneOperationType,
    ) -> ZoneValidationResult:
        """Validate whether the specified operation is permitted on the target file path."""
        zone = FourZoneScaffold.detect_zone(file_path)

        if zone == WorkspaceZone.ZONE_01_RAW and operation in (
            ZoneOperationType.WRITE,
            ZoneOperationType.DELETE,
            ZoneOperationType.RENAME,
        ):
            logger.error(
                "Violation: Attempted '%s' on protected Zone 01 asset: %s",
                operation.value,
                file_path,
            )
            raise ReadOnlySourceZoneViolationError(file_path=file_path, operation=operation.value)

        return ZoneValidationResult(
            allowed=True,
            zone=zone,
            reason=f"Operation '{operation.value}' is permitted on path",
        )

    @classmethod
    def replicate_to_draft(
        cls,
        root_dir: str,
        source_rel_path: str,
        draft_rel_path: str,
    ) -> str:
        """Safely copy a raw file from Zone 01 to Zone 02 for processing and editing."""
        root = Path(root_dir)
        src = root / WorkspaceZone.ZONE_01_RAW.value / source_rel_path
        dst = root / WorkspaceZone.ZONE_02_DRAFT.value / draft_rel_path

        if not src.exists():
            raise FileNotFoundError(f"Source file not found in Zone 01: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        logger.info("Replicated Zone 01 asset '%s' to Zone 02 draft: '%s'", src, dst)
        return str(dst)
