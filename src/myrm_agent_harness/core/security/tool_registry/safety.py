"""Built-in tool safety metadata coverage check.

[INPUT]
- tool_registry::BUILTIN_TOOL_NAMES, TOOL_SAFETY_METADATA (POS: built-in tool safety SSOT)

[OUTPUT]
- check_safety_coverage(): warn when built-in tools lack explicit safety metadata

[POS]
Module-load gate: warn when built-in tools lack explicit TOOL_SAFETY_METADATA entries.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_safety_coverage() -> None:
    """Verify all built-in tools have explicit safety declarations.

    Mirrors the governance gate scope: BUILTIN_TOOL_NAMES plus
    EXPLICIT_MCP_FALLBACK_TOOLS. Keeping both in sync here prevents a new
    EXPLICIT fallback tool from silently shipping without safety metadata.
    """
    from .registry import (
        BUILTIN_TOOL_NAMES,
        EXPLICIT_MCP_FALLBACK_TOOLS,
        TOOL_SAFETY_METADATA,
    )

    safety_required = BUILTIN_TOOL_NAMES | EXPLICIT_MCP_FALLBACK_TOOLS
    missing = safety_required - TOOL_SAFETY_METADATA.keys()
    if missing:
        logger.warning(
            "Built-in tools missing TOOL_SAFETY_METADATA (will use fail-closed defaults): %s",
            ", ".join(sorted(missing)),
        )
