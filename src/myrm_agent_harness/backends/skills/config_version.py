"""Skill config version counter for hot-reload polling.

[INPUT]
- (none)

[OUTPUT]
- bump_skill_config_version(): increment in-process version timestamp
- get_skill_config_version(): return current version (0.0 if unchanged)

[POS]
Framework-level skill config version tracker. Server and agents poll version
changes to reload skill sets without process restart.
"""

from __future__ import annotations

import time

_skill_config_versions: dict[str, float] = {}


def bump_skill_config_version() -> None:
    """Increment the skill config version.

    Agents can poll get_skill_config_version to detect changes
    and reload their skill set without restarting.
    """
    _skill_config_versions["sandbox"] = time.time()


def get_skill_config_version() -> float:
    """Return the current skill config version (0.0 if never changed)."""
    return _skill_config_versions.get("sandbox", 0.0)
