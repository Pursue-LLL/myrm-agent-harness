"""MCP tool surface mode — direct FC vs auto aggregate demotion.

[POS]
Shared enum for server profile → harness MCP routing without import cycles.

Only two routing outcomes exist at the harness layer: Direct FC Turn1 bind or
MCP→Skill (PTC). Profile value ``catalog_invoke`` parses as ``auto`` with warning.
"""

from __future__ import annotations

import logging
from enum import StrEnum

logger = logging.getLogger(__name__)


class MCPSurfaceMode(StrEnum):
    """How lightweight MCP/OpenAPI tools are exposed to the model."""

    AUTO = "auto"
    DIRECT_FC = "direct_fc"


def parse_mcp_surface_mode(raw: str | None) -> MCPSurfaceMode:
    """Parse profile/engine_params surface mode with safe default."""
    if not raw:
        return MCPSurfaceMode.AUTO
    normalized = str(raw).strip().lower()
    if normalized in {"catalog_invoke", "catalog-invoke"}:
        logger.warning(
            "mcp_surface_mode=%r is obsolete; using auto (direct vs MCP→Skill only)",
            raw,
        )
        return MCPSurfaceMode.AUTO
    try:
        return MCPSurfaceMode(normalized)
    except ValueError:
        return MCPSurfaceMode.AUTO
