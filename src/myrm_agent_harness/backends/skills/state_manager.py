"""Skill state and instance management.


[INPUT]
- backends.skills.types::SkillInstanceConfig (POS: 实例配置数据类型)
- backends.skills.types::SkillStateProtocol (POS: 状态持久化协议)
- backends.skills.types::SkillMetadata (POS: 技能元数据)
- backends.skills.types::SkillInstance (POS: 技能运行时实例,一等公民)
- backends.skills.protocols::SkillBackend (POS: 技能后端协议)

[OUTPUT]
- SkillStateManager: 状态和实例管理器(CRUD实例配置 + 保存/加载状态 + 统一加载接口load_instance)
- _validate_config_overrides(): 轻量级 JSON Schema 验证(type/enum/min/max/required)

[POS]
Skill state and instance manager. Handles instance configuration CRUD and automatic state persistence.

"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .types import SkillInstance, SkillInstanceConfig, SkillMetadata

if TYPE_CHECKING:
    from .protocols import SkillBackend

logger = logging.getLogger(__name__)

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class SkillStateManager:
    """Skill state and instance manager.

    Manages skill instances and state persistence for agent in sandbox architecture.
    All data stored in local file system (.myrm/skills/), persisted via Volume.

    Directory structure:
        .myrm/skills/
        ├── instances/          # Instance configurations
        │   ├── github/
        │   │   ├── personal.json
        │   │   └── work.json
        │   └── mysql/
        │       ├── prod.json
        │       └── dev.json
        └── states/             # Runtime state persistence
            ├── github/
            │   ├── personal.json
            │   └── work.json
            └── mysql/
                ├── prod.json
                └── dev.json

    Usage:
        # Create instance
        manager = SkillStateManager()
        manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"GITHUB_TOKEN": "ghp_xxx"},
        )

        # Load instance config
        config = manager.load_instance_config("github", "personal")

        # Save/load state (for skills implementing SkillStateProtocol)
        manager.save_skill_state(skill_metadata, "personal", {"last_repo": "foo/bar"})
        state = manager.load_skill_state(skill_metadata, "personal")
    """

    def __init__(self, base_dir: Path | str = ".myrm/skills"):
        """Initialize state manager.

        Args:
            base_dir: Base directory for skill data (default: .myrm/skills)
                     Relative to workspace root in agent in sandbox architecture.
        """
        self.base_dir = Path(base_dir)
        self.instances_dir = self.base_dir / "instances"
        self.states_dir = self.base_dir / "states"

        # Ensure directories exist
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        self.states_dir.mkdir(parents=True, exist_ok=True)

    # --- Instance Management ---

    def create_instance(
        self,
        skill_name: str,
        instance_name: str,
        env_overrides: dict[str, str] | None = None,
        config_overrides: dict[str, object] | None = None,
        config_schema: dict[str, object] | None = None,
    ) -> SkillInstanceConfig:
        """Create a new skill instance.

        Args:
            skill_name: Skill name (e.g., "github")
            instance_name: Instance name (e.g., "personal", "work")
            env_overrides: Environment variable overrides
            config_overrides: Configuration overrides

        Returns:
            SkillInstanceConfig: Created instance configuration

        Raises:
            ValueError: If instance already exists
        """
        instance_dir = self.instances_dir / skill_name
        instance_file = instance_dir / f"{instance_name}.json"

        if instance_file.exists():
            raise ValueError(f"Instance '{instance_name}' already exists for skill '{skill_name}'")

        overrides = config_overrides or {}
        if config_schema and overrides:
            _validate_config_overrides(overrides, config_schema, skill_name, instance_name)

        now = datetime.now()
        config = SkillInstanceConfig(
            instance_name=instance_name,
            skill_name=skill_name,
            created_at=now,
            updated_at=now,
            env_overrides=env_overrides or {},
            config_overrides=overrides,
            state_file=f".myrm/skills/states/{skill_name}/{instance_name}.json",
        )

        # Save to file
        instance_dir.mkdir(parents=True, exist_ok=True)
        instance_file.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")

        logger.info(f"Created skill instance: {skill_name}.{instance_name}")
        return config

    def load_instance_config(self, skill_name: str, instance_name: str) -> SkillInstanceConfig | None:
        """Load instance configuration from file.

        Args:
            skill_name: Skill name
            instance_name: Instance name

        Returns:
            SkillInstanceConfig if exists, None otherwise
        """
        instance_file = self.instances_dir / skill_name / f"{instance_name}.json"

        if not instance_file.exists():
            return None

        try:
            data = json.loads(instance_file.read_text(encoding="utf-8"))
            return SkillInstanceConfig.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load instance config {skill_name}.{instance_name}: {e}")
            return None

    def list_instances(self, skill_name: str) -> list[str]:
        """List all instances for a skill.

        Args:
            skill_name: Skill name

        Returns:
            list[str]: Instance names
        """
        instance_dir = self.instances_dir / skill_name

        if not instance_dir.exists():
            return []

        return [
            f.stem  # filename without .json extension
            for f in instance_dir.glob("*.json")
        ]

    def delete_instance(self, skill_name: str, instance_name: str) -> bool:
        """Delete skill instance and its state.

        Args:
            skill_name: Skill name
            instance_name: Instance name

        Returns:
            bool: True if deleted, False if not found
        """
        instance_file = self.instances_dir / skill_name / f"{instance_name}.json"
        state_file = self.states_dir / skill_name / f"{instance_name}.json"

        deleted = False

        if instance_file.exists():
            instance_file.unlink()
            deleted = True
            logger.info(f"Deleted instance config: {skill_name}.{instance_name}")

        if state_file.exists():
            state_file.unlink()
            logger.info(f"Deleted instance state: {skill_name}.{instance_name}")

        return deleted

    def update_instance(
        self,
        skill_name: str,
        instance_name: str,
        env_overrides: dict[str, str] | None = None,
        config_overrides: dict[str, object] | None = None,
        config_schema: dict[str, object] | None = None,
    ) -> SkillInstanceConfig | None:
        """Update an existing skill instance.

        Args:
            skill_name: Skill name
            instance_name: Instance name
            env_overrides: New environment variable overrides (replaces existing)
            config_overrides: New configuration overrides (replaces existing)

        Returns:
            SkillInstanceConfig if updated, None if not found
        """
        config = self.load_instance_config(skill_name, instance_name)

        if not config:
            return None

        config.updated_at = datetime.now()

        if env_overrides is not None:
            config.env_overrides = env_overrides

        if config_overrides is not None:
            if config_schema and config_overrides:
                _validate_config_overrides(config_overrides, config_schema, skill_name, instance_name)
            config.config_overrides = config_overrides

        # Save updated config
        instance_file = self.instances_dir / skill_name / f"{instance_name}.json"
        instance_file.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")

        logger.info(f"Updated skill instance: {skill_name}.{instance_name}")
        return config

    # --- State Persistence ---

    def save_skill_state(
        self,
        skill: SkillMetadata,
        instance_name: str,
        state: dict[str, JsonValue],
    ) -> None:
        """Save skill runtime state to file.

        For skills implementing SkillStateProtocol. Framework automatically
        calls this to persist state to .myrm/skills/states/.

        Args:
            skill: Skill metadata
            instance_name: Instance name
            state: State dict from skill.save_state()
        """
        state_dir = self.states_dir / skill.name
        state_dir.mkdir(parents=True, exist_ok=True)

        state_file = state_dir / f"{instance_name}.json"
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

        logger.debug(f"Saved state for {skill.name}.{instance_name}")

    def load_skill_state(
        self,
        skill: SkillMetadata,
        instance_name: str,
    ) -> dict[str, JsonValue] | None:
        """Load skill runtime state from file.

        For skills implementing SkillStateProtocol. Framework automatically
        calls this to restore state from .myrm/skills/states/.

        Args:
            skill: Skill metadata
            instance_name: Instance name

        Returns:
            dict if state exists, None otherwise
        """
        state_file = self.states_dir / skill.name / f"{instance_name}.json"

        if not state_file.exists():
            return None

        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load state for {skill.name}.{instance_name}: {e}")
            return None

    # --- Instance Loading (Unified Interface) ---

    async def load_instance(
        self,
        backend: SkillBackend,
        skill_name: str,
        instance_name: str,
    ) -> SkillInstance | None:
        """Load skill instance (unified interface for Agent layer).

        Composes SkillInstance by combining:
        1. Base SkillMetadata from backend (static, pure)
        2. SkillInstanceConfig from storage (env/config overrides)
        3. Runtime state from storage (persisted state)

        This is the primary entry point for Agent layer to load skill instances.
        Backend remains pure (only loads static metadata); StateManager orchestrates
        instance composition.

        Design:
        - Backend.load_skills() returns pure SkillMetadata
        - StateManager combines metadata + config + state → SkillInstance
        - Agent layer only interacts with SkillInstance objects

        Args:
            backend: Skill backend (for loading base metadata)
            skill_name: Skill name (e.g., "github_skill")
            instance_name: Instance name (e.g., "personal", "work")

        Returns:
            SkillInstance if both base skill and instance config exist, None otherwise

        Example:
            >>> backend = LocalSkillBackend()
            >>> manager = SkillStateManager()
            >>> instance = await manager.load_instance(backend, "github_skill", "personal")
            >>> if instance:
            ...     token = instance.get_env("GITHUB_TOKEN")
        """
        # 1. Load base metadata from backend
        try:
            skills = await backend.load_skills([skill_name])
            if not skills:
                logger.error(f"Skill '{skill_name}' not found in backend")
                return None
            metadata = skills[0]
        except Exception as e:
            logger.error(f"Failed to load skill '{skill_name}' from backend: {e}")
            return None

        # 2. Load instance config
        config = self.load_instance_config(skill_name, instance_name)
        if not config:
            logger.error(f"Instance config not found: {skill_name}.{instance_name}")
            return None

        # 3. Load state (returns {} if not exists)
        state = self.load_skill_state(metadata, instance_name) or {}

        # 4. Compose SkillInstance
        instance = SkillInstance(
            metadata=metadata,
            instance_name=instance_name,
            config=config,
            state=state,
        )

        logger.info(f"Loaded skill instance: {skill_name}.{instance_name}")
        return instance


_JSON_SCHEMA_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _validate_config_overrides(
    overrides: dict[str, object],
    schema: dict[str, object],
    skill_name: str,
    instance_name: str,
) -> None:
    """Lightweight JSON Schema validation for config_overrides.

    Validates type, enum, minimum/maximum, and required constraints.
    Does not implement full JSON Schema spec — only the subset relevant
    to flat-level skill configuration.

    Raises:
        ValueError: If validation fails with a clear message.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    required_fields = schema.get("required", [])
    if isinstance(required_fields, list):
        for req_field in required_fields:
            if isinstance(req_field, str) and req_field not in overrides:
                raise ValueError(
                    f"Skill '{skill_name}' instance '{instance_name}': missing required config field '{req_field}'"
                )

    errors: list[str] = []
    for key, value in overrides.items():
        prop_schema = properties.get(key)
        if not isinstance(prop_schema, dict):
            continue

        prop_type = prop_schema.get("type")
        if isinstance(prop_type, str) and prop_type in _JSON_SCHEMA_TYPE_MAP:
            expected_types = _JSON_SCHEMA_TYPE_MAP[prop_type]
            if not isinstance(value, expected_types):
                errors.append(f"field '{key}': expected {prop_type}, got {type(value).__name__}")
                continue

        enum_values = prop_schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            errors.append(f"field '{key}': value {value!r} not in allowed values {enum_values}")

        if isinstance(value, (int, float)):
            minimum = prop_schema.get("minimum")
            if isinstance(minimum, (int, float)) and value < minimum:
                errors.append(f"field '{key}': {value} < minimum {minimum}")
            maximum = prop_schema.get("maximum")
            if isinstance(maximum, (int, float)) and value > maximum:
                errors.append(f"field '{key}': {value} > maximum {maximum}")

    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"Skill '{skill_name}' instance '{instance_name}' config validation failed: {joined}")
