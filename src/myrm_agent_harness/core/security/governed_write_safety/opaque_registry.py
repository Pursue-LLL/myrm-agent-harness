"""
[POS] src/myrm_agent_harness/core/security/governed_write_safety/opaque_registry.py
[INPUT] uuid, typing
[OUTPUT] OpaqueFileRegistry
Opaque file ID registry shielding raw filesystem paths from client and model layers.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


class OpaqueFileRegistry:
    """Bi-directional mapping between secure opaque IDs and raw workspace paths."""

    def __init__(self) -> None:
        self._opaque_to_path: dict[str, str] = {}
        self._path_to_opaque: dict[str, str] = {}

    def register_path(self, raw_path: str) -> str:
        """Register or retrieve an opaque token for a raw filesystem path."""
        norm_path = raw_path.strip()
        if norm_path in self._path_to_opaque:
            return self._path_to_opaque[norm_path]

        opaque_id = f"@file_{uuid.uuid4().hex[:10]}"
        self._opaque_to_path[opaque_id] = norm_path
        self._path_to_opaque[norm_path] = opaque_id
        logger.info("Registered opaque file ID %s for path %s", opaque_id, norm_path)
        return opaque_id

    def resolve_opaque_id(self, opaque_id: str) -> str | None:
        """Resolve opaque token back to raw filesystem path in backend governance layer."""
        return self._opaque_to_path.get(opaque_id.strip())

    def get_opaque_id_for_path(self, raw_path: str) -> str | None:
        """Find registered opaque ID for a known path if present."""
        return self._path_to_opaque.get(raw_path.strip())

    def clear(self) -> None:
        """Reset registry mappings."""
        self._opaque_to_path.clear()
        self._path_to_opaque.clear()
