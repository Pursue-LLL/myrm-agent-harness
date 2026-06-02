"""Tests for subagent configuration registry."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from myrm_agent_harness.agent.sub_agents.registry import (
    SUBAGENT_CONFIGS,
    auto_register_subagent_configs,
    register_subagent_configs,
    register_subagent_configs_from_directory,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture(autouse=True)
def _clear_registry():
    saved = dict(SUBAGENT_CONFIGS)
    SUBAGENT_CONFIGS.clear()
    yield
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS.update(saved)


def _make_config(name: str = "test") -> SubagentConfig:
    return SubagentConfig(
        system_prompt=f"You are a {name} agent.",
        display_name=name.title(),
    )


def test_register_subagent_configs() -> None:
    cfg = _make_config("search")
    register_subagent_configs({"search": cfg})
    assert "search" in SUBAGENT_CONFIGS
    assert SUBAGENT_CONFIGS["search"].display_name == "Search"


def test_register_overwrites() -> None:
    cfg1 = _make_config("a")
    cfg2 = SubagentConfig(
        system_prompt="Updated prompt.",
        display_name="Updated A",
    )
    register_subagent_configs({"a": cfg1})
    register_subagent_configs({"a": cfg2})
    assert SUBAGENT_CONFIGS["a"].display_name == "Updated A"


def _write_yaml_config(directory: Path, name: str, data: dict) -> Path:
    full = {
        "name": data.get("name", name),
        "description": data.get("description", f"A {name} agent."),
        "system_prompt": data.get("system_prompt", f"You are a {name} agent."),
        "config": data.get("config", {"timeout_seconds": 60}),
        **{k: v for k, v in data.items() if k not in ("name", "description", "system_prompt", "config")},
    }
    path = directory / f"{name}.yaml"
    path.write_text(yaml.dump(full))
    return path


def test_register_from_directory() -> None:
    with TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        _write_yaml_config(d, "browser", {
            "display_name": "Browser Agent",
            "system_prompt": "Browse the web.",
        })
        result = register_subagent_configs_from_directory(str(d))
        assert "browser" in result
        assert "browser" in SUBAGENT_CONFIGS


def test_auto_register_base_path_none_raises() -> None:
    with pytest.raises(ValueError, match="base_path is required"):
        auto_register_subagent_configs(base_path=None)


def test_auto_register_core_and_custom() -> None:
    with TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        core = base / "core"
        core.mkdir()
        custom = base / "custom"
        custom.mkdir()

        _write_yaml_config(core, "search", {
            "display_name": "Core Search",
            "system_prompt": "Search.",
        })
        _write_yaml_config(custom, "search", {
            "display_name": "Custom Search",
            "system_prompt": "Custom search.",
        })

        result = auto_register_subagent_configs(base_path=str(base))
        assert result["search"].display_name == "Custom Search"
        assert SUBAGENT_CONFIGS["search"].display_name == "Custom Search"


def test_auto_register_skip_core() -> None:
    with TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        core = base / "core"
        core.mkdir()
        _write_yaml_config(core, "x", {
            "display_name": "X",
            "system_prompt": "X.",
        })

        result = auto_register_subagent_configs(base_path=str(base), load_core=False)
        assert "x" not in result


def test_auto_register_missing_dirs() -> None:
    with TemporaryDirectory() as tmpdir:
        result = auto_register_subagent_configs(base_path=tmpdir)
        assert result == {}
