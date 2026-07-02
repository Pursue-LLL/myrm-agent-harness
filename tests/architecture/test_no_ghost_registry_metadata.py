"""Architecture gate: no ghost keys in tool_registry metadata maps."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.tool_registry import (
    TOOL_CANONICAL_PARAMS,
    TOOL_GROUP_MAP,
    TOOL_PERMISSION_MAP,
    TOOL_SAFETY_METADATA,
)
from scripts.tool_registry_engine import scan


def _metadata_keys() -> set[str]:
    keys: set[str] = set(TOOL_PERMISSION_MAP)
    keys.update(TOOL_CANONICAL_PARAMS)
    keys.update(TOOL_SAFETY_METADATA)
    for tools in TOOL_GROUP_MAP.values():
        keys.update(tools)
    return keys


@pytest.mark.architecture
def test_tool_registry_metadata_has_no_ghost_tool_names() -> None:
    report = scan()
    ghosts = report.ghost_registry_metadata_keys(_metadata_keys())
    assert not ghosts, f"Ghost registry metadata keys (no @tool source): {sorted(ghosts)}"
