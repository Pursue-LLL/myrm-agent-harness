"""FactPatchRegistry for high-priority factual overrides and anti-bias patterns.

Manages persistent storage, lifecycle, and anti-bias pattern extraction for non-negotiable
user fact corrections (inspired by Kimi KDA & Hebbian memory).

[INPUT]
- myrm_agent_harness.toolkits.memory.fact_editing.models::FactPatch (POS: patch schema)
- asyncio, json, pathlib, re (POS: concurrency locking, disk persistence, and regex parsing)

[OUTPUT]
- FactPatchRegistry: Registry service managing active FactPatch collections.

[POS]
Authoritative repository for overriding stubborn pre-trained model prior biases.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from myrm_agent_harness.toolkits.memory.fact_editing.models import FactPatch

logger = logging.getLogger(__name__)

# Regular expressions detecting explicit override phrasing
_ANTI_BIAS_REGEXES: Final[tuple[re.Pattern[str], ...]] = (
    # "from X to Y", "replace X with Y"
    re.compile(r"(?:from|replace)\s+['\"]?([\w\-\./]+)['\"]?\s+(?:to|with)\s+", re.IGNORECASE),
    # "instead of X", "rather than X"
    re.compile(r"(?:instead of|rather than)\s+['\"]?([\w\-\./]+)['\"]?", re.IGNORECASE),
    # ", not X", ", never X"
    re.compile(r"(?:not|never)\s+['\"]?([\w\-\./]+)['\"]?", re.IGNORECASE),
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FactPatchRegistry:
    """Registry managing active and persistent FactPatch entities."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir
        self._lock = asyncio.Lock()
        # patch_id -> FactPatch
        self._patches: dict[str, FactPatch] = {}

        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    async def register_patch(
        self,
        entity: str,
        attribute: str,
        override_value: str,
        statement: str,
        anti_bias_patterns: list[str] | None = None,
        scope_id: str = "default",
        priority_weight: float = 1.0,
    ) -> FactPatch:
        """Register or atomically update a high-priority FactPatch."""
        async with self._lock:
            patterns = list(anti_bias_patterns or [])

            # Automatically infer anti-bias pattern from statement if none provided
            if not patterns:
                inferred = self._extract_anti_bias_patterns(statement)
                if inferred:
                    patterns.extend(inferred)

            # Check for existing patch for same entity and attribute in same scope
            for existing in self._patches.values():
                if (
                    existing.scope_id == scope_id
                    and existing.entity.strip().lower() == entity.strip().lower()
                    and existing.attribute.strip().lower() == attribute.strip().lower()
                ):
                    existing.override_value = override_value
                    existing.statement = statement
                    existing.priority_weight = priority_weight
                    existing.is_active = True
                    existing.updated_at = _utc_now()
                    # Merge unique anti-bias patterns
                    for p in patterns:
                        if p not in existing.anti_bias_patterns:
                            existing.anti_bias_patterns.append(p)
                    self._persist_to_disk_sync()
                    logger.info("Updated existing FactPatch %s for entity '%s'", existing.patch_id, entity)
                    return existing

            new_patch = FactPatch(
                entity=entity,
                attribute=attribute,
                override_value=override_value,
                statement=statement,
                anti_bias_patterns=patterns,
                scope_id=scope_id,
                priority_weight=priority_weight,
            )
            self._patches[new_patch.patch_id] = new_patch
            self._persist_to_disk_sync()
            logger.info("Registered new FactPatch %s for entity '%s'", new_patch.patch_id, entity)
            return new_patch

    async def get_active_patches(self, scope_id: str = "default") -> list[FactPatch]:
        """Retrieve all active patches applicable to the given scope."""
        async with self._lock:
            return [
                p for p in self._patches.values()
                if p.is_active and (p.scope_id == scope_id or p.scope_id == "default")
            ]

    async def deactivate_patch(self, patch_id: str) -> bool:
        """Deactivate a FactPatch by ID."""
        async with self._lock:
            patch = self._patches.get(patch_id)
            if patch and patch.is_active:
                patch.is_active = False
                patch.updated_at = _utc_now()
                self._persist_to_disk_sync()
                return True
            return False

    def _extract_anti_bias_patterns(self, text: str) -> list[str]:
        """Extract obsolete or rejected patterns from natural language override statements."""
        patterns: list[str] = []
        for pat in _ANTI_BIAS_REGEXES:
            for match in pat.finditer(text):
                token = match.group(1).strip(" .,;\"'")
                if token and len(token) > 1 and token not in patterns:
                    patterns.append(token)
        return patterns

    def _persist_to_disk_sync(self) -> None:
        """Persist registry to local JSON file if storage directory configured."""
        if not self._storage_dir:
            return
        try:
            target_file = self._storage_dir / "fact_patches.json"
            data = [p.model_dump(mode="json") for p in self._patches.values()]
            target_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist FactPatches to disk: %s", exc)

    def _load_from_disk(self) -> None:
        """Load registry from disk on initialization."""
        if not self._storage_dir:
            return
        try:
            target_file = self._storage_dir / "fact_patches.json"
            if target_file.is_file():
                raw = target_file.read_text(encoding="utf-8")
                records = json.loads(raw)
                for item in records:
                    patch = FactPatch.model_validate(item)
                    self._patches[patch.patch_id] = patch
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load FactPatches from disk: %s", exc)
