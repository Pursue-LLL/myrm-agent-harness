"""Tests for SkillStateManager CRUD operations."""

from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.state_manager import SkillStateManager


@pytest.fixture
def state_manager(tmp_path: Path) -> SkillStateManager:
    return SkillStateManager(base_dir=str(tmp_path / "skills"))


class TestCreateInstance:
    def test_create_basic(self, state_manager: SkillStateManager) -> None:
        config = state_manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"GITHUB_TOKEN": "ghp_xxx"},
            config_overrides={"timeout": 30},
        )
        assert config.instance_name == "personal"
        assert config.skill_name == "github"
        assert config.env_overrides == {"GITHUB_TOKEN": "ghp_xxx"}
        assert config.config_overrides == {"timeout": 30}

    def test_create_duplicate_raises(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        with pytest.raises(ValueError, match="already exists"):
            state_manager.create_instance(skill_name="github", instance_name="personal")

    def test_create_with_schema_validation(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
            "required": ["api_key"],
        }
        config = state_manager.create_instance(
            skill_name="search",
            instance_name="prod",
            config_overrides={"api_key": "sk-xxx"},
            config_schema=schema,
        )
        assert config.config_overrides == {"api_key": "sk-xxx"}

    def test_create_with_schema_validation_fails(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
            "required": ["api_key"],
        }
        with pytest.raises(ValueError, match="missing required config field"):
            state_manager.create_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"timeout": 30},
                config_schema=schema,
            )

    def test_create_empty_overrides(self, state_manager: SkillStateManager) -> None:
        config = state_manager.create_instance(skill_name="test", instance_name="default")
        assert config.env_overrides == {}
        assert config.config_overrides == {}


class TestListInstances:
    def test_list_empty(self, state_manager: SkillStateManager) -> None:
        result = state_manager.list_instances("nonexistent")
        assert result == []

    def test_list_multiple(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        state_manager.create_instance(skill_name="github", instance_name="work")
        result = state_manager.list_instances("github")
        assert sorted(result) == ["personal", "work"]


class TestLoadInstanceConfig:
    def test_load_existing(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "xxx"},
        )
        config = state_manager.load_instance_config("github", "personal")
        assert config is not None
        assert config.instance_name == "personal"
        assert config.env_overrides == {"TOKEN": "xxx"}

    def test_load_nonexistent(self, state_manager: SkillStateManager) -> None:
        config = state_manager.load_instance_config("github", "missing")
        assert config is None


class TestUpdateInstance:
    def test_update_overrides(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "old"},
            config_overrides={"timeout": 10},
        )
        updated = state_manager.update_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "new"},
            config_overrides={"timeout": 60},
        )
        assert updated is not None
        assert updated.env_overrides == {"TOKEN": "new"}
        assert updated.config_overrides == {"timeout": 60}

    def test_update_nonexistent(self, state_manager: SkillStateManager) -> None:
        result = state_manager.update_instance(
            skill_name="github",
            instance_name="missing",
            env_overrides={"TOKEN": "xxx"},
        )
        assert result is None

    def test_update_partial(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "xxx"},
            config_overrides={"timeout": 10},
        )
        updated = state_manager.update_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "new"},
        )
        assert updated is not None
        assert updated.env_overrides == {"TOKEN": "new"}
        assert updated.config_overrides == {"timeout": 10}


class TestDeleteInstance:
    def test_delete_existing(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        result = state_manager.delete_instance("github", "personal")
        assert result is True
        config = state_manager.load_instance_config("github", "personal")
        assert config is None

    def test_delete_nonexistent(self, state_manager: SkillStateManager) -> None:
        result = state_manager.delete_instance("github", "missing")
        assert result is False
