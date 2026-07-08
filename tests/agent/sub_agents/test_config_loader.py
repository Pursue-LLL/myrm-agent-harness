from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

"""Unit tests for SubagentConfigLoader"""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.config_loader import (
    SubagentConfigLoader,
    load_subagent_configs_from_directory,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for test config files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def valid_config_yaml():
    """Valid subagent configuration YAML content"""
    return """
name: test_agent
description: Test agent for unit tests
tools:
  - web_search_tool
  - web_fetch_tool
system_prompt: |
  You are a test agent.
  Be helpful and accurate.
config:
  timeout_seconds: 60
  concurrency_limit: 5
  max_turns: 10
  max_retries: 2
  retry_backoff_seconds: 1.5
  max_spawn_depth: 1
  budget_tokens: 1000
  max_result_tokens: 500
"""


@pytest.fixture
def minimal_config_yaml():
    """Minimal valid configuration (using defaults)"""
    return """
name: minimal_agent
description: Minimal agent with defaults
tools: []
system_prompt: |
  Minimal prompt.
config: {}
"""


@pytest.fixture
def invalid_config_yaml():
    """Invalid configuration (missing required fields)"""
    return """
name: invalid_agent
# Missing description, tools, system_prompt
config:
  timeout_seconds: 60
"""


class TestSubagentConfigLoader:
    """Test SubagentConfigLoader class"""

    def test_load_valid_config(self, temp_config_dir, valid_config_yaml):
        """Test loading a valid configuration file"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(valid_config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert isinstance(config, SubagentConfig)
        assert config.description == "Test agent for unit tests"
        assert config.tools == ("web_search_tool", "web_fetch_tool")
        assert "test agent" in config.system_prompt.lower()
        assert config.timeout_seconds == 60
        assert config.concurrency_limit == 5
        assert config.max_turns == 10
        assert config.max_retries == 2
        assert config.retry_backoff_seconds == 1.5
        assert config.max_spawn_depth == 1
        assert config.budget_tokens == 1000
        assert config.max_result_tokens == 500

    def test_load_minimal_config_with_defaults(self, temp_config_dir, minimal_config_yaml):
        """Test loading minimal config uses default values"""
        config_file = temp_config_dir / "minimal.yaml"
        config_file.write_text(minimal_config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.description == "Minimal agent with defaults"
        assert config.tools == ()
        assert config.timeout_seconds == 120  # default
        assert config.concurrency_limit == 5  # default
        assert config.max_spawn_depth == 0  # default

    def test_load_nonexistent_file(self, temp_config_dir):
        """Test loading non-existent file returns None"""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(temp_config_dir / "nonexistent.yaml")

        assert config is None

    def test_load_invalid_yaml(self, temp_config_dir):
        """Test loading invalid YAML returns None"""
        config_file = temp_config_dir / "invalid.yaml"
        config_file.write_text("invalid: yaml: content: [")

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_load_invalid_config_structure(self, temp_config_dir, invalid_config_yaml):
        """Test loading config with missing required fields returns None"""
        config_file = temp_config_dir / "invalid.yaml"
        config_file.write_text(invalid_config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_load_invalid_tool_name(self, temp_config_dir):
        """Test config with invalid tool name is rejected"""
        config_yaml = """
name: test
description: Test
tools:
  - web_search_tool
  - invalid-tool-name!  # Invalid: contains !
system_prompt: Test
config: {}
"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_rejects_unknown_ssot_tool_name(self, temp_config_dir):
        """Test config with syntactically valid but unregistered tool names is rejected."""
        config_yaml = """
name: test
description: Test
tools:
  - browser_click
system_prompt: Test prompt here.
config: {}
"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_load_file_too_large(self, temp_config_dir):
        """Test file size limit protection"""
        config_file = temp_config_dir / "large.yaml"
        # Create a config file that exceeds the limit
        large_content = "name: test\ndescription: Test\ntools: []\nsystem_prompt: " + ("x" * 200_000)
        config_file.write_text(large_content)

        loader = SubagentConfigLoader(max_file_size=100_000)  # 100 KB limit
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_load_from_directory(self, temp_config_dir, valid_config_yaml, minimal_config_yaml):
        """Test loading multiple configs from a directory"""
        # File name must match YAML name field
        (temp_config_dir / "test_agent.yaml").write_text(valid_config_yaml)
        (temp_config_dir / "minimal_agent.yaml").write_text(minimal_config_yaml)

        loader = SubagentConfigLoader()
        configs = loader.load_from_directory(temp_config_dir)

        assert len(configs) == 2
        assert "test_agent" in configs
        assert "minimal_agent" in configs
        assert isinstance(configs["test_agent"], SubagentConfig)
        assert isinstance(configs["minimal_agent"], SubagentConfig)

    def test_load_from_directory_with_invalid_files(self, temp_config_dir, valid_config_yaml):
        """Test directory loading skips invalid files"""
        # File name must match YAML name field
        (temp_config_dir / "test_agent.yaml").write_text(valid_config_yaml)
        (temp_config_dir / "invalid.yaml").write_text("invalid: yaml: [")

        loader = SubagentConfigLoader()
        configs = loader.load_from_directory(temp_config_dir)

        assert len(configs) == 1
        assert "test_agent" in configs
        assert "invalid" not in configs

    def test_load_from_nonexistent_directory(self, temp_config_dir):
        """Test loading from non-existent directory returns empty dict"""
        loader = SubagentConfigLoader()
        configs = loader.load_from_directory(temp_config_dir / "nonexistent")

        assert configs == {}

    def test_load_from_empty_directory(self, temp_config_dir):
        """Test loading from empty directory returns empty dict"""
        loader = SubagentConfigLoader()
        configs = loader.load_from_directory(temp_config_dir)

        assert configs == {}

    def test_disallowed_tools(self, temp_config_dir):
        """Test loading config with disallowed_tools"""
        config_yaml = """
name: test
description: Test agent with disallowed tools
tools:
  - web_search_tool
disallowed_tools:
  - skill_manage_tool
  - skill_discovery_tool
system_prompt: |
  You are a test agent.
config: {}
"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.disallowed_tools == frozenset({"skill_manage_tool", "skill_discovery_tool"})

    def test_load_model_and_display_name(self, temp_config_dir):
        """Test that model and display_name fields are parsed from YAML."""
        config_yaml = """
name: research
description: Research agent
display_name: "研究助手"
model: "openai/gpt-4o-mini"
tools:
  - web_search_tool
system_prompt: |
  You are a research agent.
config:
  timeout_seconds: 30
"""
        config_file = temp_config_dir / "research.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.model == "openai/gpt-4o-mini"
        assert config.display_name == "研究助手"

    def test_model_and_display_name_default_to_empty(self, temp_config_dir, minimal_config_yaml):
        """Test that model/display_name default correctly when not specified."""
        config_file = temp_config_dir / "minimal_agent.yaml"
        config_file.write_text(minimal_config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.model is None
        assert config.display_name == ""

    def test_theme_color_parsed_correctly(self, temp_config_dir):
        """Test that theme_color is correctly parsed and passed to SubagentConfig."""
        config_yaml = """
name: colored
description: Agent with theme color
display_name: "Colored Agent"
theme_color: "cyan"
tools:
  - web_search_tool
system_prompt: |
  You are a colored agent.
config:
  timeout_seconds: 30
"""
        config_file = temp_config_dir / "colored.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.theme_color == "cyan"

    def test_theme_color_defaults_to_empty(self, temp_config_dir, minimal_config_yaml):
        """Test that theme_color defaults to empty string when not specified."""
        config_file = temp_config_dir / "minimal_agent.yaml"
        config_file.write_text(minimal_config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is not None
        assert config.theme_color == ""

    def test_invalid_theme_color_rejected(self, temp_config_dir):
        """Test that invalid theme_color values are rejected by schema validation."""
        config_yaml = """
name: bad_color
description: Agent with invalid color
theme_color: "neon_green"
tools: []
system_prompt: |
  You are a test agent.
config: {}
"""
        config_file = temp_config_dir / "bad_color.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_long_system_prompt_rejected(self, temp_config_dir):
        """Test system prompt length limit"""
        config_yaml = f"""
name: test
description: Test
tools: []
system_prompt: {"x" * 15000}  # Exceeds 10K limit
config: {{}}
"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(config_file)

        assert config is None

    def test_invalid_config_name_characters_rejected(self, temp_config_dir):
        """Test schema rejects non-alphanumeric config names."""
        config_yaml = """
name: bad name!
description: Test
tools: []
system_prompt: Valid prompt here.
config: {}
"""
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        assert loader.load_from_yaml(config_file) is None

    def test_yaml_root_not_dict_rejected(self, temp_config_dir):
        config_file = temp_config_dir / "test.yaml"
        config_file.write_text("- not_a_dict\n")

        loader = SubagentConfigLoader()
        assert loader.load_from_yaml(config_file) is None

    def test_expected_name_mismatch_rejected(self, temp_config_dir, valid_config_yaml):
        config_file = temp_config_dir / "test_agent.yaml"
        config_file.write_text(valid_config_yaml)

        loader = SubagentConfigLoader()
        assert loader.load_from_yaml(config_file, expected_name="other_agent") is None

    def test_invalid_enum_and_context_mode_rejected(self, temp_config_dir):
        config_yaml = """
name: enum_test
description: Test enum validation
tools:
  - web_search_tool
system_prompt: Valid prompt here.
config:
  cancellation_strategy: not_a_strategy
"""
        config_file = temp_config_dir / "enum_test.yaml"
        config_file.write_text(config_yaml)

        loader = SubagentConfigLoader()
        assert loader.load_from_yaml(config_file) is None

        config_yaml_invalid_context = """
name: ctx_test
description: Test context mode validation
tools:
  - web_search_tool
system_prompt: Valid prompt here.
config:
  context_mode: invalid_mode
"""
        config_file2 = temp_config_dir / "ctx_test.yaml"
        config_file2.write_text(config_yaml_invalid_context)
        assert loader.load_from_yaml(config_file2) is None

    def test_load_from_file_path_instead_of_directory(self, temp_config_dir, valid_config_yaml):
        config_file = temp_config_dir / "test_agent.yaml"
        config_file.write_text(valid_config_yaml)

        loader = SubagentConfigLoader()
        assert loader.load_from_directory(config_file) == {}

def test_convenience_function(temp_config_dir, valid_config_yaml):
    """Test convenience function load_subagent_configs_from_directory"""
    # File name must match YAML name field
    (temp_config_dir / "test_agent.yaml").write_text(valid_config_yaml)

    configs = load_subagent_configs_from_directory(temp_config_dir)

    assert len(configs) == 1
    assert "test_agent" in configs
    assert isinstance(configs["test_agent"], SubagentConfig)


def test_load_real_core_configs():
    """Integration test: Load actual core configs from configs/subagents/core/"""
    core_configs_path = Path(__file__).parent.parent.parent.parent / "configs" / "subagents" / "core"

    if not core_configs_path.exists():
        pytest.skip("Core configs directory not found")

    configs = load_subagent_configs_from_directory(core_configs_path)

    # Should load at least search, browser, analysis
    assert len(configs) >= 3
    assert "search" in configs or "browser" in configs or "analysis" in configs

    # Verify all loaded configs are valid SubagentConfig instances
    for _name, config in configs.items():
        assert isinstance(config, SubagentConfig)
        assert config.system_prompt
        assert config.timeout_seconds > 0


class TestCodingYamlIntegration:
    """Integration tests for coding.yaml subagent preset."""

    @pytest.fixture
    def coding_yaml_path(self):
        """Path to the real coding.yaml file in myrm-agent-server."""
        monorepo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        path = (
            monorepo_root
            / "myrm-agent"
            / "myrm-agent-server"
            / "app"
            / "config"
            / "subagents"
            / "core"
            / "coding.yaml"
        )
        if not path.exists():
            pytest.skip("coding.yaml not found (run tests from harness repo root)")
        return path

    def test_coding_yaml_loads_successfully(self, coding_yaml_path):
        """Test that coding.yaml is syntactically valid and loadable."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert isinstance(config, SubagentConfig)

    def test_coding_yaml_has_required_tools(self, coding_yaml_path):
        """Test that coding preset includes essential coding tools."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        essential_tools = {
            "bash_code_execute_tool",
            "file_read_tool",
            "file_write_tool",
            "file_edit_tool",
            "grep_tool",
            "glob_tool",
        }
        assert essential_tools.issubset(set(config.tools))

    def test_coding_yaml_has_delegate_capability(self, coding_yaml_path):
        """Test that coding preset can delegate to external agents."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert "delegate_to_agent_tool" in config.tools

    def test_coding_yaml_blocks_privileged_tools(self, coding_yaml_path):
        """Test that coding preset correctly blocks skill management tools."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert "skill_manage_tool" in config.disallowed_tools
        assert "skill_discovery_tool" in config.disallowed_tools

    def test_coding_yaml_uses_fork_context(self, coding_yaml_path):
        """Test that coding preset uses fork context mode for cache preservation."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert config.context_mode == "fork"

    def test_coding_yaml_theme_color(self, coding_yaml_path):
        """Test that coding preset has a valid theme color."""
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert config.theme_color == "cyan"

    def test_coding_yaml_workspace_inherits(self, coding_yaml_path):
        """Test that coding preset inherits workspace from parent."""
        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(coding_yaml_path, expected_name="coding")

        assert config is not None
        assert config.workspace_policy == WorkspacePolicy.INHERIT


class TestDeepAuditYamlIntegration:
    """Integration tests for deep-audit.yaml subagent preset."""

    @pytest.fixture
    def deep_audit_yaml_path(self):
        monorepo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        path = (
            monorepo_root
            / "myrm-agent"
            / "myrm-agent-server"
            / "app"
            / "config"
            / "subagents"
            / "core"
            / "deep-audit.yaml"
        )
        if not path.exists():
            pytest.skip("deep-audit.yaml not found")
        return path

    def test_deep_audit_loads_successfully(self, deep_audit_yaml_path):
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        assert isinstance(config, SubagentConfig)

    def test_deep_audit_read_only_tools(self, deep_audit_yaml_path):
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        assert set(config.tools) == {"file_read_tool", "grep_tool", "glob_tool", "bash_code_execute_tool"}
        write_tools = {"file_write_tool", "file_edit_tool", "skill_manage_tool", "skill_discovery_tool", "delegate_to_agent_tool"}
        assert write_tools.issubset(config.disallowed_tools)

    def test_deep_audit_no_delegation(self, deep_audit_yaml_path):
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        assert config.max_spawn_depth == 0
        assert "delegate_to_agent_tool" in config.disallowed_tools

    def test_deep_audit_config_values(self, deep_audit_yaml_path):
        from myrm_agent_harness.agent.sub_agents.types import MemoryIsolationPolicy, WorkspacePolicy

        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        assert config.timeout_seconds == 600
        assert config.concurrency_limit == 5
        assert config.max_turns == 30
        assert config.budget_tokens == 500000
        assert config.max_result_tokens == 16000
        assert config.workspace_policy == WorkspacePolicy.INHERIT
        assert config.memory_isolation == MemoryIsolationPolicy.EPHEMERAL_SESSION
        assert config.context_mode == "isolated"

    def test_deep_audit_theme_color(self, deep_audit_yaml_path):
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        assert config.theme_color == "orange"

    def test_deep_audit_prompt_focuses_on_logic_flaws(self, deep_audit_yaml_path):
        loader = SubagentConfigLoader()
        config = loader.load_from_yaml(deep_audit_yaml_path, expected_name="deep-audit")

        assert config is not None
        prompt = config.system_prompt.lower()
        assert "business logic bypass" in prompt
        assert "privilege escalation" in prompt
        assert "race condition" in prompt
        assert "data exfiltration" in prompt
        assert "prompt injection" in prompt
