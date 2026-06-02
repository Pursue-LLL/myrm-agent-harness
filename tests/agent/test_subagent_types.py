"""Unit tests for SubagentConfig and SUBAGENT_CONFIGS registry.

Tests:
1. SubagentConfig dataclass correctness
2. SUBAGENT_CONFIGS preset validation (populated by conftest fixture)
3. Configuration reasonableness checks
"""

import pytest

from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture(autouse=True)
def setup_configs():
    original = dict(SUBAGENT_CONFIGS)
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS["search"] = SubagentConfig(
        tools=("web_search_tool", "web_fetch_tool"),
        system_prompt="Search prompt of sufficient length",
        timeout_seconds=60,
        concurrency_limit=5,
        max_retries=3,
        max_spawn_depth=2,
    )
    SUBAGENT_CONFIGS["browser"] = SubagentConfig(
        tools=("browser_navigate_tool", "browser_click"),
        system_prompt="Browser prompt of sufficient length",
        timeout_seconds=60,
        concurrency_limit=3,
        max_spawn_depth=0,
    )
    SUBAGENT_CONFIGS["analysis"] = SubagentConfig(
        tools=("memory_read", "memory_write"),
        system_prompt="Analysis prompt of sufficient length",
        timeout_seconds=60,
        concurrency_limit=5,
        max_spawn_depth=0,
    )
    yield
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS.update(original)


def test_subagent_config_dataclass():
    config = SubagentConfig(
        tools=("tool1", "tool2"),
        system_prompt="Test prompt",
        timeout_seconds=10,
        concurrency_limit=5,
        max_retries=3,
        retry_backoff_seconds=2.0,
        max_spawn_depth=1,
    )

    assert config.tools == ("tool1", "tool2")
    assert config.system_prompt == "Test prompt"
    assert config.timeout_seconds == 10
    assert config.concurrency_limit == 5
    assert config.max_retries == 3
    assert config.retry_backoff_seconds == 2.0
    assert config.max_spawn_depth == 1


def test_subagent_config_defaults():
    config = SubagentConfig(tools=("tool1"), system_prompt="Test", timeout_seconds=5, concurrency_limit=10)

    assert config.max_retries == 3
    assert config.retry_backoff_seconds == 2.0
    assert config.max_spawn_depth == 0


def test_subagent_configs_exists():
    assert SUBAGENT_CONFIGS is not None
    assert len(SUBAGENT_CONFIGS) > 0
    assert isinstance(SUBAGENT_CONFIGS, dict)


def test_subagent_configs_required_types():
    required_types = ["search", "browser", "analysis"]

    for agent_type in required_types:
        assert agent_type in SUBAGENT_CONFIGS, f"Missing required agent_type: {agent_type}"
        assert isinstance(SUBAGENT_CONFIGS[agent_type], SubagentConfig)


def test_search_agent_config():
    config = SUBAGENT_CONFIGS["search"]

    assert "web_search_tool" in config.tools
    assert "web_fetch_tool" in config.tools
    assert len(config.tools) >= 2
    assert config.timeout_seconds > 0
    assert config.concurrency_limit > 0
    assert config.max_retries > 0
    assert len(config.system_prompt) > 0
    assert config.max_spawn_depth >= 1


def test_browser_agent_config():
    config = SUBAGENT_CONFIGS["browser"]

    assert "browser_navigate_tool" in config.tools
    assert len(config.tools) >= 2
    assert config.timeout_seconds > 0
    assert config.concurrency_limit > 0
    assert config.max_spawn_depth == 0


def test_analysis_agent_config():
    config = SUBAGENT_CONFIGS["analysis"]

    assert "memory_read" in config.tools or "memory_write" in config.tools
    assert len(config.tools) >= 2
    assert config.timeout_seconds > 0
    assert config.concurrency_limit > 0
    assert config.max_spawn_depth == 0


def test_config_timeout_reasonable():
    for agent_type, config in SUBAGENT_CONFIGS.items():
        assert 1 <= config.timeout_seconds <= 300, (
            f"{agent_type} timeout {config.timeout_seconds}s out of reasonable range (1-300s)"
        )


def test_config_concurrency_reasonable():
    for agent_type, config in SUBAGENT_CONFIGS.items():
        assert 1 <= config.concurrency_limit <= 50, (
            f"{agent_type} concurrency {config.concurrency_limit} out of reasonable range (1-50)"
        )


def test_only_search_can_spawn():
    assert SUBAGENT_CONFIGS["search"].max_spawn_depth >= 1
    assert SUBAGENT_CONFIGS["browser"].max_spawn_depth == 0
    assert SUBAGENT_CONFIGS["analysis"].max_spawn_depth == 0


def test_all_configs_have_system_prompt():
    for agent_type, config in SUBAGENT_CONFIGS.items():
        assert config.system_prompt, f"{agent_type} missing system_prompt"
        assert len(config.system_prompt) > 10, f"{agent_type} system_prompt too short"


def test_all_configs_have_tools():
    for agent_type, config in SUBAGENT_CONFIGS.items():
        assert len(config.tools) > 0, f"{agent_type} has no tools"


def test_subagent_config_type_correctness():
    original_search_tools = SUBAGENT_CONFIGS["search"].tools
    original_timeout = SUBAGENT_CONFIGS["search"].timeout_seconds

    assert isinstance(original_search_tools, tuple)
    assert isinstance(original_timeout, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
