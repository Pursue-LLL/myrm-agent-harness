"""Session Evidence read-only file protection validator.

Physically blocks write operations (CREATE, STR_REPLACE) to files residing in
protected evidence directories (such as `evidence/`, `user_inputs/`).
Ensures models cannot tamper with or overwrite raw factual inputs pulled by tools
or supplied by humans.

[INPUT]
- myrm_agent_harness.core.security.path_security::is_evidence_readonly_file (POS: evidence path security check)
- core.operation_context::OperationContext, OperationType (POS: operation context)

[OUTPUT]
- EvidenceReadOnlyValidator: class — Validator protecting raw evidence files from overwrite

[POS]
Harness Agent Layer — Meta tools file ops validator chain component.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.path_security import is_evidence_readonly_file

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class EvidenceReadOnlyValidator(Validator):
    """Blocks write operations to protected session evidence and raw input assets."""

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        if context.operation == OperationType.VIEW:
            return

        if is_evidence_readonly_file(path):
            logger.warning(
                "[EvidenceReadOnlyValidator] BLOCKED write to read-only evidence path: %s",
                path,
            )
            raise PermissionError(
                f"BLOCKED: '{path}' resides in a read-only session evidence or user input directory. "
                f"Raw evidence and source materials are immutable to ensure tamper-evident audit trails. "
                f"Please write intermediate artifacts or output deliverables to 'working/' or 'artifacts/' instead."
            )
