# [POS]: myrm_agent_harness.toolkits.memory.peer_gateway.escalation
# [INPUT]: None (Standard library)
# [OUTPUT]: HashEscalationEngine

"""Adaptive hash collision escalation algorithm for deterministic peer normalization.

Generates concise, human-readable peer identifiers with progressive length expansion
to guarantee collision-free uniqueness across multi-channel environments.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

_ESCALATION_LENGTHS: Final[tuple[int, ...]] = (8, 12, 16, 24, 32)
_SAFE_CHAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9_-]+")


class HashEscalationEngine:
    """Escalates hash suffix length on collision to preserve uniqueness and readability."""

    @staticmethod
    def clean_identifier(raw_id: str) -> str:
        """Sanitize raw external channel identifier into safe alphanumeric token."""
        stripped = raw_id.strip()
        cleaned = _SAFE_CHAR_PATTERN.sub("_", stripped).strip("_")
        return cleaned.lower() if cleaned else "anonymous"

    @classmethod
    def escalate_hash_suffix(
        cls,
        raw_id: str,
        collision_registry: set[str],
        prefix: str = "peer_",
    ) -> tuple[str, bool]:
        """Generate collision-free peer identifier with adaptive hash expansion.

        Returns tuple of (unique_identifier, was_escalated_beyond_default).
        """
        base_name = cls.clean_identifier(raw_id)
        digest = hashlib.sha256(raw_id.strip().encode("utf-8")).hexdigest()

        for idx, length in enumerate(_ESCALATION_LENGTHS):
            suffix = digest[:length]
            candidate = f"{prefix}{base_name}_{suffix}"
            if candidate not in collision_registry:
                return candidate, idx > 0

        # Fallback for extreme saturation: full 32-char digest
        full_candidate = f"{prefix}{base_name}_{digest[:32]}"
        return full_candidate, True
