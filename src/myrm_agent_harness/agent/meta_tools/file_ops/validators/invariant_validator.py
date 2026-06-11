"""Goal-scoped invariant file protection validator.

Physically blocks write operations to files matching the active Goal's
``protected_paths`` glob patterns. This is the pre-emptive enforcement layer
— it prevents modifications **before** they happen, complementing the
post-hoc hash integrity check in CompletionGuard.

[INPUT]
- agent.middlewares._session_context::get_protected_paths (POS: ContextVar for Goal-scoped protected patterns)

[OUTPUT]
- InvariantValidator: class — Goal-scoped invariant file protection validator

[POS]
Provides InvariantValidator.
"""

from __future__ import annotations

import logging
from fnmatch import fnmatch
from typing import TYPE_CHECKING

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class InvariantValidator(Validator):
    """Blocks write operations to Goal-protected files.

    Reads the active Goal's protected_paths from the session ContextVar and
    rejects any CREATE or STR_REPLACE targeting a matching path.
    """

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        if context.operation == OperationType.VIEW:
            return

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_protected_paths,
        )

        patterns = get_protected_paths()
        if not patterns:
            return

        for pattern in patterns:
            if fnmatch(path, pattern):
                logger.warning(
                    "[InvariantValidator] BLOCKED write to protected path: %s (pattern: %s)",
                    path,
                    pattern,
                )
                raise PermissionError(
                    f"BLOCKED: '{path}' is protected by the current Goal's invariant guard "
                    f"(matched pattern: '{pattern}').\n"
                    f"This file must not be modified during this Goal execution.\n"
                    f"If you need to modify this file, ask the user to remove the "
                    f"protection via the Goal settings."
                )
