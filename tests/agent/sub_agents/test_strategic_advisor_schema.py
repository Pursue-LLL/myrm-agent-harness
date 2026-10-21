"""Unit tests for Strategic Advisor 4-section schema and loader integration."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from myrm_agent_harness.agent.sub_agents.config_loader import (
    SubagentConfigLoader,
    load_subagent_configs_from_directory,
)
from myrm_agent_harness.agent.sub_agents.strategic_advisor_schema import (
    READONLY_FORBIDDEN_TOOLS,
    StrategicAdvisorySchema,
    StrategicIdentitySchema,
    StrategicOutputProtocolSchema,
    StrategicScopeSchema,
    compile_strategic_advisor_prompt,
    validate_strategic_readonly_safety,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


class TestStrategicAdvisorSchema:
    """Test 4-section schema definitions and safety validations."""

    def test_valid_advisory_schema(self) -> None:
        schema = StrategicAdvisorySchema(
            identity=StrategicIdentitySchema(
                role="Strategic Architecture Advisor",
                description="Expert architect reviewing designs.",
            ),
            scope=StrategicScopeSchema(
                mode="readonly",
                tools=["file_read_tool", "grep_tool"],
                disallowed_tools=["file_write_tool"],
            ),
            advisory_principles=[
                "First-Principles: Question conventional designs.",
                "Zero Technical Debt: Forward-looking refactoring.",
            ],
            output_protocol=StrategicOutputProtocolSchema(
                format="markdown",
                required_sections=["Executive Summary", "Directives"],
            ),
        )
        assert schema.identity.role == "Strategic Architecture Advisor"
        assert schema.scope.mode == "readonly"
        assert len(schema.advisory_principles) == 2

    def test_scope_must_be_readonly(self) -> None:
        with pytest.raises(ValidationError):
            StrategicScopeSchema(mode="readwrite")  # type: ignore[arg-type]

    def test_validate_strategic_readonly_safety_pass(self) -> None:
        scope = StrategicScopeSchema(mode="readonly")
        # Read-only tools should pass
        validate_strategic_readonly_safety(scope, ["file_read_tool", "grep_tool", "glob_tool"])

    def test_validate_strategic_readonly_safety_fail_on_mutation_tools(self) -> None:
        scope = StrategicScopeSchema(mode="readonly")
        for bad_tool in READONLY_FORBIDDEN_TOOLS:
            with pytest.raises(ValueError, match="Read-only strategic advisor cannot possess write/mutation tools"):
                validate_strategic_readonly_safety(scope, ["file_read_tool", bad_tool])

    def test_compile_strategic_advisor_prompt(self) -> None:
        schema = StrategicAdvisorySchema(
            identity=StrategicIdentitySchema(
                role="Principal Systems Strategist",
                description="Provides unvarnished architectural critique.",
            ),
            scope=StrategicScopeSchema(mode="readonly"),
            advisory_principles=[
                "Performance First: Eliminate redundant compute.",
                "Anti-Sycophancy: Challenge bad assumptions.",
            ],
            output_protocol=StrategicOutputProtocolSchema(
                required_sections=[
                    "Executive Summary",
                    "Critical Architectural Flaws",
                    "Actionable Directives",
                ]
            ),
        )
        prompt = compile_strategic_advisor_prompt(schema)
        assert "Principal Systems Strategist" in prompt
        assert "Strict read-only mode" in prompt
        assert "Performance First" in prompt
        assert "Anti-Sycophancy" in prompt
        assert "Critical Architectural Flaws" in prompt
        assert "Actionable Directives" in prompt


class TestStrategicAdvisorConfigLoader:
    """Test loader support for 4-section strategic advisor YAML."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_load_strategic_advisor_yaml_with_compiled_prompt(self, temp_dir: Path) -> None:
        yaml_content = """
name: strategic-advisor
display_name: "Strategic Advisor"
theme_color: "purple"

identity:
  role: "Chief Architecture Advisor"
  description: "World-class system architect specializing in unsycophantic design review."

scope:
  mode: "readonly"
  tools:
    - file_read_tool
    - grep_tool
    - glob_tool
  disallowed_tools:
    - file_write_tool
    - file_edit_tool
    - bash_code_execute_tool

advisory_principles:
  - "First-Principles Thinking: Rigorously analyze system boundaries."
  - "High Performance: Eliminate unnecessary complexity and I/O."
  - "Pure Refactoring: Zero legacy debt compromises."

output_protocol:
  format: "markdown"
  required_sections:
    - "Executive Summary"
    - "Architectural Vulnerabilities"
    - "Actionable Strategic Directives"

config:
  timeout_seconds: 90
  concurrency_limit: 3
  max_turns: 15
"""
        config_path = temp_dir / "strategic-advisor.yaml"
        config_path.write_text(yaml_content, encoding="utf-8")

        loader = SubagentConfigLoader()
        cfg = loader.load_from_yaml(config_path, expected_name="strategic-advisor")

        assert cfg is not None
        assert isinstance(cfg, SubagentConfig)
        assert cfg.is_advisory is True
        assert cfg.advisory_schema is not None
        assert cfg.description == "World-class system architect specializing in unsycophantic design review."
        assert cfg.tools == ("file_read_tool", "grep_tool", "glob_tool")
        assert "file_write_tool" in cfg.disallowed_tools
        assert "Chief Architecture Advisor" in cfg.system_prompt
        assert "Strict read-only mode" in cfg.system_prompt
        assert "Architectural Vulnerabilities" in cfg.system_prompt
        assert cfg.timeout_seconds == 90

    def test_reject_strategic_advisor_with_write_tool(self, temp_dir: Path) -> None:
        yaml_content = """
name: dangerous-advisor
description: "Illegal advisor with write tool"

identity:
  role: "Faulty Advisor"
  description: "Attempts write tool"

scope:
  mode: "readonly"
  tools:
    - file_read_tool
    - file_write_tool

advisory_principles:
  - "Principle 1"

config: {}
"""
        config_path = temp_dir / "dangerous-advisor.yaml"
        config_path.write_text(yaml_content, encoding="utf-8")

        loader = SubagentConfigLoader()
        cfg = loader.load_from_yaml(config_path)
        assert cfg is None

    def test_batch_load_from_directory_includes_advisory(self, temp_dir: Path) -> None:
        advisory_yaml = """
name: my-advisor
identity:
  role: "Advisor"
  description: "Strategic advisor"
scope:
  mode: "readonly"
  tools:
    - file_read_tool
advisory_principles:
  - "Review carefully"
config: {}
"""
        normal_yaml = """
name: normal-worker
description: "Normal subagent"
tools:
  - file_read_tool
system_prompt: "You are a helpful subagent worker."
config: {}
"""
        (temp_dir / "my-advisor.yaml").write_text(advisory_yaml, encoding="utf-8")
        (temp_dir / "normal-worker.yaml").write_text(normal_yaml, encoding="utf-8")

        configs = load_subagent_configs_from_directory(temp_dir)
        assert len(configs) == 2
        assert configs["my-advisor"].is_advisory is True
        assert configs["normal-worker"].is_advisory is False
