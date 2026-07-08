"""Subagent configuration loader.

Loads subagent configurations from YAML files with strict validation.
Supports directory-level batch loading and graceful error handling.

[INPUT]
- agent.tool_management.tool_layers::is_registered_action_tool (POS: Tool layer priority registry. Defines CORE/COMMON/EXTENDED three-tier tool priorities used by ToolRegistry for ordering.)
- agent.types::SubagentConfig (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- SubagentConfigLoader: YAML configuration loader with typed enum validation and Action Tool SSOT checks.
- load_subagent_configs_from_directory(): Convenience function for directory-level loading.

[POS]
External config loader. Loads subagent configurations from YAML files with strict validation and fallback strategies.

"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from myrm_agent_harness.agent.tool_management.tool_layers import is_registered_action_tool
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .types import (
    CancellationStrategy,
    ControlScope,
    MemoryIsolationPolicy,
    SubagentConfig,
    WorkspacePolicy,
)

logger = get_agent_logger(__name__)

_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_MAX_CONFIG_FILE_SIZE = 100 * 1024  # 100 KB
_MAX_SYSTEM_PROMPT_LENGTH = 10000  # 10K chars


def _validate_tools_against_ssot(tool_names: list[str], file_path: Path) -> bool:
    """Reject tool names that are not registered in the Action Tool SSOT (_TOOL_LAYERS)."""
    unknown = sorted({name for name in tool_names if not is_registered_action_tool(name)})
    if not unknown:
        return True
    logger.error(
        "Unknown tool name(s) in %s: %s. Register tools in tool_layers._TOOL_LAYERS before use.",
        file_path,
        unknown,
    )
    return False


def _enum_from_config[EnumT: StrEnum](
    enum_cls: type[EnumT],
    raw_value: object,
    default_value: EnumT,
) -> EnumT:
    if raw_value is None:
        return default_value
    try:
        return enum_cls(str(raw_value))
    except ValueError as error:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"Invalid {enum_cls.__name__} value '{raw_value}'. Allowed: {allowed}") from error


class SubagentConfigSchema(BaseModel):
    """Pydantic schema for validating YAML subagent configuration.

    Provides strict validation beyond SubagentConfig dataclass.
    """

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    display_name: str = Field(default="", max_length=200)
    theme_color: str = Field(default="", max_length=20, pattern=r"^(|blue|green|purple|orange|pink|cyan|amber|red)$")
    model: str | None = Field(default=None, max_length=200)
    tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    system_prompt: str = Field(min_length=10)
    config: dict[str, object]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid name '{v}': must be alphanumeric with _ or -")
        return v

    @field_validator("tools", "disallowed_tools")
    @classmethod
    def validate_tool_names(cls, v: list[str]) -> list[str]:
        for tool_name in v:
            if not _TOOL_NAME_PATTERN.match(tool_name):
                raise ValueError(f"Invalid tool name '{tool_name}': must match {_TOOL_NAME_PATTERN.pattern}")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str) -> str:
        if len(v) > _MAX_SYSTEM_PROMPT_LENGTH:
            raise ValueError(f"System prompt too long: {len(v)} > {_MAX_SYSTEM_PROMPT_LENGTH}")
        return v


class SubagentConfigLoader:
    """Loads and validates subagent configurations from YAML files.

    Features:
    - Strict schema validation via Pydantic
    - File size limits (DoS protection)
    - Tool name validation (injection prevention)
    - Graceful error handling with detailed logging
    - Batch directory loading
    """

    def __init__(self, max_file_size: int = _MAX_CONFIG_FILE_SIZE) -> None:
        """Initialize loader with optional file size limit.

        Args:
            max_file_size: Maximum allowed config file size in bytes (default 100KB)
        """
        self.max_file_size = max_file_size

    def load_from_yaml(self, file_path: str | Path, expected_name: str | None = None) -> SubagentConfig | None:
        """Load and validate a single subagent configuration from YAML file.

        Args:
            file_path: Path to YAML configuration file
            expected_name: Expected config name (from filename). If provided, validates YAML name matches.

        Returns:
            SubagentConfig instance if successful, None if loading/validation failed

        Error Handling:
            - File not found → log warning, return None
            - File too large → log error, return None
            - Invalid YAML → log error, return None
            - Schema validation failed → log error with details, return None
            - Name mismatch (if expected_name provided) → log error, return None
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.warning("Config file not found: %s", file_path)
            return None

        # Check file size (DoS protection)
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            logger.error(
                "Config file too large: %s (%d bytes > %d bytes limit)", file_path, file_size, self.max_file_size
            )
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            if not isinstance(raw_data, dict):
                logger.error("Config file %s has invalid format (expected dict, got %s)", file_path, type(raw_data))
                return None

            # Validate with Pydantic schema
            try:
                validated = SubagentConfigSchema(**raw_data)
            except ValidationError as e:
                logger.error("Config validation failed for %s:\n%s", file_path, e)
                return None

            # Validate name if expected_name provided
            if expected_name is not None and validated.name != expected_name:
                logger.error(
                    "Config name mismatch: YAML has 'name: %s' but expected '%s'. "
                    "Name field must match filename for consistency.",
                    validated.name,
                    expected_name,
                )
                return None

            all_tool_refs = list(validated.tools) + list(validated.disallowed_tools)
            if not _validate_tools_against_ssot(all_tool_refs, file_path):
                return None

            # Convert to SubagentConfig dataclass
            config_dict = validated.config
            raw_vault_threshold = config_dict.get("auto_vault_threshold", 8000)
            auto_vault_threshold = int(raw_vault_threshold) if raw_vault_threshold is not None else None
            cancellation_strategy = _enum_from_config(
                CancellationStrategy,
                config_dict.get("cancellation_strategy"),
                CancellationStrategy.GRACEFUL,
            )
            memory_isolation = _enum_from_config(
                MemoryIsolationPolicy,
                config_dict.get("memory_isolation"),
                MemoryIsolationPolicy.EPHEMERAL_SESSION,
            )
            control_scope = _enum_from_config(
                ControlScope,
                config_dict.get("control_scope"),
                ControlScope.LEAF,
            )
            workspace_policy = _enum_from_config(
                WorkspacePolicy,
                config_dict.get("workspace_policy"),
                WorkspacePolicy.INHERIT,
            )
            context_mode_raw = str(config_dict.get("context_mode", "isolated"))
            if context_mode_raw not in {"isolated", "fork"}:
                raise ValueError("Invalid context_mode value. Allowed: isolated, fork")
            context_mode = cast(Literal["isolated", "fork"], context_mode_raw)

            subagent_config = SubagentConfig(
                system_prompt=validated.system_prompt,
                tools=tuple(validated.tools),
                disallowed_tools=frozenset(validated.disallowed_tools),
                description=validated.description,
                display_name=validated.display_name,
                theme_color=validated.theme_color,
                model=validated.model,
                timeout_seconds=config_dict.get("timeout_seconds", 120),
                concurrency_limit=config_dict.get("concurrency_limit", 5),
                max_turns=config_dict.get("max_turns", 25),
                max_retries=config_dict.get("max_retries", 3),
                retry_backoff_seconds=config_dict.get("retry_backoff_seconds", 2.0),
                max_spawn_depth=config_dict.get("max_spawn_depth", 0),
                budget_tokens=config_dict.get("budget_tokens"),
                max_cost_usd=config_dict.get("max_cost_usd"),
                max_result_tokens=config_dict.get("max_result_tokens"),
                max_children_per_agent=int(config_dict.get("max_children_per_agent", 5)),
                max_descendants_per_run=int(config_dict.get("max_descendants_per_run", 20)),
                max_batch_size=int(config_dict.get("max_batch_size", 5)),
                auto_vault_threshold=auto_vault_threshold,
                cancellation_strategy=cancellation_strategy,
                graceful_cancel_timeout_seconds=float(config_dict.get("graceful_cancel_timeout_seconds", 5.0)),
                memory_isolation=memory_isolation,
                control_scope=control_scope,
                workspace_policy=workspace_policy,
                context_mode=context_mode,
                max_fork_tokens=config_dict.get("max_fork_tokens"),
            )

            logger.info("Loaded subagent config '%s' from %s", validated.name, file_path)
            return subagent_config

        except yaml.YAMLError as e:
            logger.error("Failed to parse YAML file %s: %s", file_path, e)
            return None
        except Exception as e:
            logger.error("Unexpected error loading config from %s: %s", file_path, e, exc_info=True)
            return None

    def load_from_directory(self, dir_path: str | Path, pattern: str = "*.yaml") -> dict[str, SubagentConfig]:
        """Load all subagent configurations from a directory.

        Args:
            dir_path: Directory containing YAML configuration files
            pattern: Glob pattern for config files (default "*.yaml")

        Returns:
            Dictionary mapping subagent names to SubagentConfig instances.
            Files that fail to load are logged and skipped.

        Example:
            >>> loader = SubagentConfigLoader()
            >>> configs = loader.load_from_directory("configs/subagents/core")
            >>> print(configs.keys())
            dict_keys(['search', 'browser', 'analysis'])
        """
        dir_path = Path(dir_path)

        if not dir_path.exists():
            logger.warning("Config directory not found: %s", dir_path)
            return {}

        if not dir_path.is_dir():
            logger.error("Path is not a directory: %s", dir_path)
            return {}

        configs: dict[str, SubagentConfig] = {}
        config_files = sorted(dir_path.glob(pattern))

        if not config_files:
            logger.info("No config files matching '%s' found in %s", pattern, dir_path)
            return {}

        logger.info("Loading %d config file(s) from %s", len(config_files), dir_path)

        for config_file in config_files:
            # Extract expected name from filename
            expected_name = config_file.stem

            # Load config with name validation
            subagent_config = self.load_from_yaml(config_file, expected_name=expected_name)
            if subagent_config is not None:
                configs[expected_name] = subagent_config
            else:
                logger.warning("Skipping config file %s due to loading failure", config_file)

        logger.info("Successfully loaded %d/%d config(s) from %s", len(configs), len(config_files), dir_path)

        return configs


def load_subagent_configs_from_directory(dir_path: str | Path, pattern: str = "*.yaml") -> dict[str, SubagentConfig]:
    """Convenience function to load subagent configs from a directory.

        Args:
            dir_path: Directory containing YAML configuration files
            pattern: Glob pattern for config files (default "*.yaml")

        Returns:
            Dictionary mapping subagent names to SubagentConfig instances

        Example:
            >>> from myrm_agent_harness.agent.sub_agents.config_loader import load_subagent_configs_from_directory
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
            >>> configs = load_subagent_configs_from_directory("configs/subagents/core")
    """
    loader = SubagentConfigLoader()
    return loader.load_from_directory(dir_path, pattern)
