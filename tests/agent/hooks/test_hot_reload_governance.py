"""Loading-surface governance for config-loaded hooks (hot_reload stamping).

The loader, not the file, owns priority bounds: malformed priorities fail
closed (that hook is skipped) without poisoning sibling hooks, and valid ones
are capped below the security band while keeping user-level ordering intact.
Provenance stamping itself is covered in test_hooks.py::TestHotReload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.hooks import CommandHookDefinition
from myrm_agent_harness.agent.hooks.hot_reload import HookReloader
from myrm_agent_harness.core.hooks.types import HOOK_PRIORITY_SECURITY, HookDefinition


def _load_pre_tool_hooks(tmp_path: Path, entries: list[dict[str, object]]) -> list[HookDefinition]:
    config = tmp_path / "hooks.json"
    config.write_text(json.dumps({"hooks": {"pre_tool_use": entries}}))
    return HookReloader(config).current_registry().get("pre_tool_use")


@pytest.mark.parametrize("bad_priority", [-5, None, "abc"], ids=["negative", "null", "non-numeric"])
def test_malformed_priority_skips_only_that_hook(tmp_path: Path, bad_priority: object) -> None:
    hooks = _load_pre_tool_hooks(
        tmp_path,
        [
            {"type": "command", "command": "echo bad", "priority": bad_priority},
            {"type": "command", "command": "echo good"},
        ],
    )
    assert len(hooks) == 1
    survivor = hooks[0]
    assert isinstance(survivor, CommandHookDefinition)
    assert survivor.command == "echo good"


@pytest.mark.parametrize(
    "raw_priority",
    [HOOK_PRIORITY_SECURITY, 1500, "1500", 2000.5],
    ids=["exactly-at-band", "above-band", "numeric-string", "float"],
)
def test_priority_reaching_security_band_is_capped_below_it(tmp_path: Path, raw_priority: object) -> None:
    hooks = _load_pre_tool_hooks(tmp_path, [{"type": "command", "command": "echo x", "priority": raw_priority}])
    assert hooks[0].priority == HOOK_PRIORITY_SECURITY - 1


def test_priorities_below_band_keep_relative_order(tmp_path: Path) -> None:
    """The cap must not flatten legitimate ordering among user-level hooks."""
    hooks = _load_pre_tool_hooks(
        tmp_path,
        [
            {"type": "command", "command": "echo low", "priority": 10},
            {"type": "command", "command": "echo high", "priority": 20},
        ],
    )
    assert [hook.priority for hook in hooks] == [20, 10]
