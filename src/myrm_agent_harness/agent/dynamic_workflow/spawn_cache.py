"""Spawn cache key helpers for DW durable execution.

[POS]
See module docstring.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class SpawnCacheParams:
    """Parameters that must match for a durable cache hit."""

    agent_type: str
    task_description: str
    readonly: bool
    verification_mode: Literal["none", "adversarial"]
    verifier_agent_type: str | None
    max_verification_rounds: int

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()


def spawn_cache_params_from_json(raw: str) -> SpawnCacheParams | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return SpawnCacheParams(
            agent_type=str(data["agent_type"]),
            task_description=str(data["task_description"]),
            readonly=bool(data["readonly"]),
            verification_mode=data["verification_mode"],
            verifier_agent_type=data.get("verifier_agent_type"),
            max_verification_rounds=int(data["max_verification_rounds"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
