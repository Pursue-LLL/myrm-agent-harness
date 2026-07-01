"""Skill instance configuration, state protocol, and runtime instance.

[INPUT]
- types_metadata.SkillMetadata (POS: base skill metadata)

[OUTPUT]
- SkillInstanceConfig: per-instance env/config overrides with validation
- SkillStateProtocol: optional state persistence protocol for skills
- SkillInstance: runtime instance combining metadata, config, and state

[POS]
Multi-instance skill runtime types composed by StateManager for agent execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata


@dataclass
class SkillInstanceConfig:
    """Skill instance configuration for multi-instance support.

    Stored in .myrm/skills/instances/{skill_name}/{instance_name}.json
    Enables multiple instances of the same skill with different configurations.

    Example use cases:
    - github (personal/work): Different API tokens
    - mysql (prod/dev): Different connection strings
    - monitoring (server-1/server-2): Different hosts
    """

    instance_name: str
    """Instance name (e.g., 'personal', 'work', 'prod', 'dev')"""

    skill_name: str
    """Skill name this instance belongs to"""

    created_at: datetime
    """Timestamp when instance was created"""

    updated_at: datetime
    """Timestamp when instance was last updated"""

    env_overrides: dict[str, str] = field(default_factory=dict)
    """Environment variable overrides for this instance.

    Example: {"GITHUB_TOKEN": "ghp_personal_xxx", "GITHUB_ORG": "my-org"}
    These override the default env vars when this instance is loaded.
    """

    config_overrides: dict[str, object] = field(default_factory=dict)
    """Configuration overrides for this instance.

    Example: {"api_base_url": "https://api.custom.com", "timeout": 30}
    Skill-specific configurations that differ per instance.
    """

    state_file: str | None = None
    """Relative path to state file for this instance.

    Example: ".myrm/skills/states/{skill_name}/{instance_name}.json"
    Auto-generated when state persistence is enabled.
    """

    def __post_init__(self) -> None:
        """Validate instance configuration after initialization.

        Validates:
        - instance_name: Non-empty, no whitespace, alphanumeric + underscore/dash only
        - skill_name: Non-empty
        - env_overrides: Keys are non-empty strings, values are non-empty strings
        - config_overrides: Values are JSON-serializable
        """
        import re

        # Validate instance_name
        if not self.instance_name or not isinstance(self.instance_name, str):
            raise ValueError("instance_name must be a non-empty string")
        if self.instance_name != self.instance_name.strip():
            raise ValueError("instance_name cannot contain leading/trailing whitespace")
        if not re.match(r"^[a-zA-Z0-9_-]+$", self.instance_name):
            raise ValueError("instance_name must contain only alphanumeric characters, underscores, and dashes")

        # Validate skill_name
        if not self.skill_name or not isinstance(self.skill_name, str):
            raise ValueError("skill_name must be a non-empty string")

        # Validate env_overrides
        if not isinstance(self.env_overrides, dict):
            raise ValueError("env_overrides must be a dict")
        for key, value in self.env_overrides.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"env_overrides key must be non-empty string, got: {key!r}")
            if not isinstance(value, str):
                raise ValueError(f"env_overrides value must be string, got {type(value).__name__} for key {key!r}")

        # Validate config_overrides
        if not isinstance(self.config_overrides, dict):
            raise ValueError("config_overrides must be a dict")

    def to_dict(self) -> dict[str, object]:
        """Serialize instance config to dict for JSON storage."""
        return {
            "instance_name": self.instance_name,
            "skill_name": self.skill_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "env_overrides": self.env_overrides,
            "config_overrides": self.config_overrides,
            "state_file": self.state_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SkillInstanceConfig:
        """Deserialize instance config from dict with validation."""
        return cls(
            instance_name=str(data["instance_name"]),
            skill_name=str(data["skill_name"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            updated_at=datetime.fromisoformat(str(data["updated_at"])),
            env_overrides=dict(data.get("env_overrides", {})),  # type: ignore
            config_overrides=dict(data.get("config_overrides", {})),  # type: ignore
            state_file=str(data["state_file"]) if data.get("state_file") else None,
        )


class SkillStateProtocol:
    """Protocol for skills that support state persistence.

    Skills implement this protocol to enable automatic state save/load.
    Framework handles serialization to .myrm/skills/states/{skill}/{instance}.json

    Example implementation:
        class GitHubSkill(SkillStateProtocol):
            def save_state(self) -> dict[str, object]:
                return {
                    "last_repo": self.current_repo,
                    "cached_prs": self.pr_cache,
                }

            def load_state(self, state: dict[str, object]) -> None:
                self.current_repo = state.get("last_repo")
                self.pr_cache = state.get("cached_prs", {})
    """

    def save_state(self) -> dict[str, object]:
        """Save skill state to dict.

        Framework serializes this to JSON and stores in:
        .myrm/skills/states/{skill_name}/{instance_name}.json

        Returns:
            dict: State data to persist (JSON-serializable)
        """
        raise NotImplementedError

    def load_state(self, state: dict[str, object]) -> None:
        """Load skill state from dict.

        Called by framework after deserializing JSON state file.
        Skill should restore its internal state from the provided dict.

        Args:
            state: State data loaded from .myrm/skills/states/
        """
        raise NotImplementedError


@dataclass
class SkillInstance:
    """Skill runtime instance (first-class object).

    Represents a concrete skill instance combining:
    - Base metadata (static, from SkillBackend)
    - Instance configuration (overrides)
    - Runtime state (persisted)

    This is the primary object Agent layer interacts with. Backend loads pure
    SkillMetadata; StateManager composes SkillInstance by combining metadata,
    config, and state.

    Design principles:
    1. Pure value object (immutable semantics)
    2. Single source of truth for instance execution
    3. Backend agnostic (works with any SkillBackend)

    Example:
        # Load via StateManager (unified interface)
        instance = state_manager.load_instance("github_skill", "personal")

        # Access merged environment
        token = instance.get_env("GITHUB_TOKEN")  # Instance override priority

        # Access base metadata
        print(instance.metadata.description)

        # Access instance config
        print(instance.config.created_at)
    """

    metadata: SkillMetadata
    """Base skill metadata (static, from SkillBackend)"""

    instance_name: str
    """Instance name (e.g., 'personal', 'work', 'prod', 'dev')"""

    config: SkillInstanceConfig
    """Instance-specific configuration (env/config overrides)"""

    state: dict[str, object]
    """Runtime state (persisted across sessions, JSON-serializable)"""

    def get_env(self, key: str, default: str | None = None) -> str | None:
        """Get environment variable with instance override priority.

        Fallback order:
        1. Instance env_overrides (highest priority)
        2. System environment variables (os.environ)
        3. Default parameter (fallback)

        Args:
            key: Environment variable name
            default: Default value if key not in overrides or system env

        Returns:
            Value from instance overrides, system env, or default
        """
        import os

        # 1. Check instance overrides first
        if key in self.config.env_overrides:
            return self.config.env_overrides[key]

        # 2. Fallback to system environment
        return os.environ.get(key, default)

    def get_config(self, key: str, default: object = None) -> object:
        """Get configuration value with instance override priority.

        Returns value from instance config_overrides, or default if not found.

        Args:
            key: Configuration key
            default: Default value if key not in instance overrides

        Returns:
            Value from instance overrides or default
        """
        return self.config.config_overrides.get(key, default)
