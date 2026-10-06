"""Loading-surface governance for config-loaded hooks (hot_reload stamping).

The loader, not the file, owns priority bounds: malformed priorities fail
closed (that hook is skipped) without poisoning sibling hooks, and valid ones
are capped below the security band while keeping user-level ordering intact.
Provenance stamping is unit-covered in test_hooks.py::TestHotReload; here the
stamp is exercised end-to-end through the executor's strict command gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.hooks import CommandHookDefinition, HookEvent, HookExecutor, HookRegistry
from myrm_agent_harness.agent.hooks.hot_reload import HookReloader
from myrm_agent_harness.core.hooks.types import HOOK_PRIORITY_SECURITY, HookDefinition

_EVENT = HookEvent.PRE_TOOL_USE


def _load_registry(tmp_path: Path, entries: list[dict[str, object]]) -> HookRegistry:
    config = tmp_path / "hooks.json"
    config.write_text(json.dumps({"hooks": {_EVENT.value: entries}}))
    return HookReloader(config).current_registry()


def _load_pre_tool_hooks(tmp_path: Path, entries: list[dict[str, object]]) -> list[HookDefinition]:
    return _load_registry(tmp_path, entries).get(_EVENT)


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


@pytest.mark.asyncio
async def test_config_hook_claiming_builtin_cannot_unlock_escalated_command(tmp_path: Path) -> None:
    """Attack chain: a config file self-declares builtin to fire an ESCALATE-level command silently."""
    registry = _load_registry(tmp_path, [{"type": "command", "command": "eval true", "source": "builtin"}])
    result = await HookExecutor(registry).execute(_EVENT, {})
    assert result.results[0].success is False
    assert result.results[0].metadata["gate_blocked"] is True


@pytest.mark.asyncio
async def test_config_hook_with_benign_command_still_runs(tmp_path: Path) -> None:
    """Positive control: the strict gate narrows config hooks without disabling them."""
    registry = _load_registry(tmp_path, [{"type": "command", "command": "echo config-ok"}])
    result = await HookExecutor(registry).execute(_EVENT, {})
    assert result.results[0].success is True
    assert "config-ok" in result.results[0].output
