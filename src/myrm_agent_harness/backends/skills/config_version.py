"""Skill config version counter for hot-reload polling.

[INPUT]
- myrm_agent_harness.infra.atomic_write::atomic_write (POS: Atomic file write with crash-consistency guarantee.)
- MYRM_DATA_DIR (optional infra env): persistent data root; default ~/.myrm

[OUTPUT]
- bump_skill_config_version(): persist a monotonic version timestamp on Volume
- get_skill_config_version(): read current version (0.0 if never changed)

[POS]
Framework-level skill config version tracker. Stored under MYRM_DATA_DIR so
API workers and long-lived agents in the same sandbox share invalidation state.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)

_VERSION_FILENAME = ".skill_config_version"


def _resolve_myrm_data_root() -> Path:
    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    return Path.home() / ".myrm"


def _version_path() -> Path:
    return _resolve_myrm_data_root() / _VERSION_FILENAME


def bump_skill_config_version() -> None:
    """Increment the skill config version.

    Agents can poll get_skill_config_version to detect changes
    and reload their skill set without restarting.
    """
    version = time.time()
    atomic_write(_version_path(), f"{version:.6f}\n")


def get_skill_config_version() -> float:
    """Return the current skill config version (0.0 if never changed)."""
    path = _version_path()
    if not path.is_file():
        return 0.0
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Failed to read skill config version file %s: %s", path, exc)
        return 0.0
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid skill config version in %s: %r", path, raw)
        return 0.0
