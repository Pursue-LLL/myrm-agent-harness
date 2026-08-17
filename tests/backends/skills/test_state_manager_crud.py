"""Tests for SkillStateManager CRUD operations."""

from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.state_manager import SkillStateManager
from myrm_agent_harness.backends.skills.types import SkillMetadata


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

    def test_create_with_schema_validation(
        self, state_manager: SkillStateManager
    ) -> None:
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

    def test_create_with_schema_validation_fails(
        self, state_manager: SkillStateManager
    ) -> None:
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
        config = state_manager.create_instance(
            skill_name="test", instance_name="default"
        )
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

    def test_load_corrupted_json_returns_none(
        self, state_manager: SkillStateManager
    ) -> None:
        instance_file = state_manager.instances_dir / "github" / "broken.json"
        instance_file.parent.mkdir(parents=True, exist_ok=True)
        instance_file.write_text("{not valid json", encoding="utf-8")
        assert state_manager.load_instance_config("github", "broken") is None


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

    def test_update_with_schema_validation(
        self, state_manager: SkillStateManager
    ) -> None:
        state_manager.create_instance(skill_name="search", instance_name="prod")
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
            "required": ["api_key"],
        }
        updated = state_manager.update_instance(
            skill_name="search",
            instance_name="prod",
            config_overrides={"api_key": "sk-xxx"},
            config_schema=schema,
        )
        assert updated is not None
        assert updated.config_overrides == {"api_key": "sk-xxx"}

    def test_update_with_schema_validation_fails(
        self, state_manager: SkillStateManager
    ) -> None:
        state_manager.create_instance(skill_name="search", instance_name="prod")
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"api_key": {"type": "string"}},
            "required": ["api_key"],
        }
        with pytest.raises(ValueError, match="missing required config field"):
            state_manager.update_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"timeout": 30},
                config_schema=schema,
            )


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

    def test_delete_removes_state_file(self, state_manager: SkillStateManager) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        skill = SkillMetadata(name="github", description="test")
        state_manager.save_skill_state(skill, "personal", {"last_repo": "foo/bar"})
        state_file = state_manager.states_dir / "github" / "personal.json"
        assert state_file.exists()
        result = state_manager.delete_instance("github", "personal")
        assert result is True
        assert not state_file.exists()


class TestSkillStatePersistence:
    def test_save_and_load_roundtrip(self, state_manager: SkillStateManager) -> None:
        skill = SkillMetadata(name="github", description="test")
        state_manager.save_skill_state(
            skill, "personal", {"last_repo": "foo/bar", "count": 3}
        )
        loaded = state_manager.load_skill_state(skill, "personal")
        assert loaded == {"last_repo": "foo/bar", "count": 3}

    def test_load_missing_state_returns_none(
        self, state_manager: SkillStateManager
    ) -> None:
        skill = SkillMetadata(name="github", description="test")
        assert state_manager.load_skill_state(skill, "missing") is None

    def test_load_non_object_state_returns_none(
        self, state_manager: SkillStateManager
    ) -> None:
        skill = SkillMetadata(name="github", description="test")
        state_file = state_manager.states_dir / "github" / "personal.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert state_manager.load_skill_state(skill, "personal") is None

    def test_load_corrupted_state_returns_none(
        self, state_manager: SkillStateManager
    ) -> None:
        skill = SkillMetadata(name="github", description="test")
        state_file = state_manager.states_dir / "github" / "personal.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{broken", encoding="utf-8")
        assert state_manager.load_skill_state(skill, "personal") is None

    def test_save_state_leaves_no_tmp_residue(
        self, state_manager: SkillStateManager
    ) -> None:
        skill = SkillMetadata(name="github", description="test")
        state_manager.save_skill_state(skill, "personal", {"k": "v"})
        residue = [
            p
            for p in (state_manager.states_dir / "github").iterdir()
            if p.name.startswith(".atomic_")
        ]
        assert residue == []


class TestConfigOverrideValidation:
    def test_type_mismatch_raises(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"timeout": {"type": "integer"}},
        }
        with pytest.raises(ValueError, match="expected integer"):
            state_manager.create_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"timeout": "not-an-int"},
                config_schema=schema,
            )

    def test_enum_violation_raises(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}},
        }
        with pytest.raises(ValueError, match="not in allowed values"):
            state_manager.create_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"mode": "turbo"},
                config_schema=schema,
            )

    def test_minimum_violation_raises(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"timeout": {"type": "integer", "minimum": 10}},
        }
        with pytest.raises(ValueError, match="< minimum"):
            state_manager.create_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"timeout": 5},
                config_schema=schema,
            )

    def test_maximum_violation_raises(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"timeout": {"type": "integer", "maximum": 100}},
        }
        with pytest.raises(ValueError, match="> maximum"):
            state_manager.create_instance(
                skill_name="search",
                instance_name="prod",
                config_overrides={"timeout": 200},
                config_schema=schema,
            )

    def test_unknown_property_skipped(self, state_manager: SkillStateManager) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"timeout": {"type": "integer"}},
        }
        config = state_manager.create_instance(
            skill_name="search",
            instance_name="prod",
            config_overrides={"unknown_field": "value"},
            config_schema=schema,
        )
        assert config.config_overrides == {"unknown_field": "value"}

    def test_non_dict_properties_skipped(
        self, state_manager: SkillStateManager
    ) -> None:
        schema: dict[str, object] = {"type": "object", "properties": "not-a-dict"}
        config = state_manager.create_instance(
            skill_name="search",
            instance_name="prod",
            config_overrides={"timeout": 30},
            config_schema=schema,
        )
        assert config.config_overrides == {"timeout": 30}


class TestLoadInstance:
    @pytest.mark.asyncio
    async def test_load_instance_composes(
        self, state_manager: SkillStateManager
    ) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.backends.skills.protocols import SkillBackend

        skill = SkillMetadata(name="github", description="test")
        backend = AsyncMock(spec=SkillBackend)
        backend.load_skills.return_value = [skill]
        state_manager.create_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "xxx"},
        )
        state_manager.save_skill_state(skill, "personal", {"last_repo": "foo/bar"})

        instance = await state_manager.load_instance(backend, "github", "personal")

        assert instance is not None
        assert instance.instance_name == "personal"
        assert instance.metadata.name == "github"
        assert instance.config.env_overrides == {"TOKEN": "xxx"}
        assert instance.state == {"last_repo": "foo/bar"}

    @pytest.mark.asyncio
    async def test_load_instance_skill_not_found(
        self, state_manager: SkillStateManager
    ) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.backends.skills.protocols import SkillBackend

        backend = AsyncMock(spec=SkillBackend)
        backend.load_skills.return_value = []
        assert await state_manager.load_instance(backend, "github", "personal") is None

    @pytest.mark.asyncio
    async def test_load_instance_backend_error(
        self, state_manager: SkillStateManager
    ) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.backends.skills.protocols import SkillBackend

        backend = AsyncMock(spec=SkillBackend)
        backend.load_skills.side_effect = RuntimeError("backend down")
        assert await state_manager.load_instance(backend, "github", "personal") is None

    @pytest.mark.asyncio
    async def test_load_instance_config_missing(
        self, state_manager: SkillStateManager
    ) -> None:
        from unittest.mock import AsyncMock

        from myrm_agent_harness.backends.skills.protocols import SkillBackend

        skill = SkillMetadata(name="github", description="test")
        backend = AsyncMock(spec=SkillBackend)
        backend.load_skills.return_value = [skill]
        assert await state_manager.load_instance(backend, "github", "personal") is None


class TestAtomicPersistence:
    def test_create_leaves_no_tmp_residue(
        self, state_manager: SkillStateManager
    ) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        residue = [
            p
            for p in (state_manager.instances_dir / "github").iterdir()
            if p.name.startswith(".atomic_")
        ]
        assert residue == []

    def test_update_leaves_no_tmp_residue(
        self, state_manager: SkillStateManager
    ) -> None:
        state_manager.create_instance(skill_name="github", instance_name="personal")
        state_manager.update_instance(
            skill_name="github",
            instance_name="personal",
            env_overrides={"TOKEN": "new"},
        )
        residue = [
            p
            for p in (state_manager.instances_dir / "github").iterdir()
            if p.name.startswith(".atomic_")
        ]
        assert residue == []
