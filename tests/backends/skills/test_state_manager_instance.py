"""Tests for SkillStateManager.load_instance method.

Tests the unified interface for loading skill instances, combining
base metadata, instance config, and runtime state.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.backends.skills.state_manager import SkillStateManager
from myrm_agent_harness.backends.skills.types import SkillInstance, SkillInstanceConfig, SkillMetadata


@pytest.fixture
def state_manager(tmp_path: Path) -> SkillStateManager:
    """Create state manager with temp directory."""
    return SkillStateManager(base_dir=tmp_path / ".myrm/skills")


@pytest.fixture
def mock_backend() -> MagicMock:
    """Create mock SkillBackend."""
    backend = MagicMock()
    backend.load_skills = AsyncMock()
    return backend


@pytest.fixture
def base_metadata() -> SkillMetadata:
    """Create base skill metadata."""
    return SkillMetadata(
        name="github_skill",
        description="GitHub integration skill",
        storage_skill_id="github_001",
    )


@pytest.fixture
def instance_config(state_manager: SkillStateManager) -> SkillInstanceConfig:
    """Create and save instance config."""
    config = state_manager.create_instance(
        skill_name="github_skill",
        instance_name="personal",
        env_overrides={"GITHUB_TOKEN": "ghp_xxx"},
        config_overrides={"api_base_url": "https://api.github.com"},
    )
    return config


@pytest.fixture
def instance_state(state_manager: SkillStateManager, base_metadata: SkillMetadata) -> dict[str, Any]:
    """Create and save instance state."""
    state = {"last_repo": "foo/bar", "cached_prs": ["#123"]}
    state_manager.save_skill_state(base_metadata, "personal", state)
    return state


@pytest.mark.asyncio
async def test_load_instance_success(
    state_manager: SkillStateManager,
    mock_backend: MagicMock,
    base_metadata: SkillMetadata,
    instance_config: SkillInstanceConfig,
    instance_state: dict[str, Any],
) -> None:
    """Test successful instance loading."""
    mock_backend.load_skills.return_value = [base_metadata]

    instance = await state_manager.load_instance(
        backend=mock_backend,
        skill_name="github_skill",
        instance_name="personal",
    )

    assert instance is not None
    assert isinstance(instance, SkillInstance)
    assert instance.metadata == base_metadata
    assert instance.instance_name == "personal"
    assert instance.config == instance_config
    assert instance.state == instance_state

    # Verify backend was called correctly
    mock_backend.load_skills.assert_called_once_with(["github_skill"])


@pytest.mark.asyncio
async def test_load_instance_skill_not_found(
    state_manager: SkillStateManager,
    mock_backend: MagicMock,
    instance_config: SkillInstanceConfig,
) -> None:
    """Test instance loading when skill not found in backend."""
    mock_backend.load_skills.return_value = []

    instance = await state_manager.load_instance(
        backend=mock_backend,
        skill_name="github_skill",
        instance_name="personal",
    )

    assert instance is None


@pytest.mark.asyncio
async def test_load_instance_config_not_found(
    state_manager: SkillStateManager,
    mock_backend: MagicMock,
    base_metadata: SkillMetadata,
) -> None:
    """Test instance loading when instance config not found."""
    mock_backend.load_skills.return_value = [base_metadata]

    instance = await state_manager.load_instance(
        backend=mock_backend,
        skill_name="github_skill",
        instance_name="nonexistent",
    )

    assert instance is None


@pytest.mark.asyncio
async def test_load_instance_without_state(
    state_manager: SkillStateManager,
    mock_backend: MagicMock,
    base_metadata: SkillMetadata,
    instance_config: SkillInstanceConfig,
) -> None:
    """Test instance loading when state file doesn't exist."""
    mock_backend.load_skills.return_value = [base_metadata]

    instance = await state_manager.load_instance(
        backend=mock_backend,
        skill_name="github_skill",
        instance_name="personal",
    )

    assert instance is not None
    assert instance.state == {}


@pytest.mark.asyncio
async def test_load_instance_backend_error(
    state_manager: SkillStateManager,
    mock_backend: MagicMock,
    instance_config: SkillInstanceConfig,
) -> None:
    """Test instance loading when backend raises error."""
    mock_backend.load_skills.side_effect = Exception("Backend error")

    instance = await state_manager.load_instance(
        backend=mock_backend,
        skill_name="github_skill",
        instance_name="personal",
    )

    assert instance is None


def test_skill_instance_get_env(
    state_manager: SkillStateManager,
    base_metadata: SkillMetadata,
    instance_config: SkillInstanceConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test SkillInstance.get_env method with fallback order."""

    instance = SkillInstance(
        metadata=base_metadata,
        instance_name="personal",
        config=instance_config,
        state={},
    )

    # 1. Test getting override value (highest priority)
    assert instance.get_env("GITHUB_TOKEN") == "ghp_xxx"

    # 2. Test fallback to system environment
    monkeypatch.setenv("SYSTEM_VAR", "system_value")
    assert instance.get_env("SYSTEM_VAR") == "system_value"

    # 3. Test fallback to default parameter
    assert instance.get_env("NONEXISTENT", "default") == "default"

    # 4. Test getting None when all fallbacks fail
    assert instance.get_env("NONEXISTENT") is None

    # 5. Test instance override takes precedence over system env
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_system")
    assert instance.get_env("GITHUB_TOKEN") == "ghp_xxx"  # Instance override wins


def test_skill_instance_get_config(
    state_manager: SkillStateManager,
    base_metadata: SkillMetadata,
    instance_config: SkillInstanceConfig,
) -> None:
    """Test SkillInstance.get_config method."""
    instance = SkillInstance(
        metadata=base_metadata,
        instance_name="personal",
        config=instance_config,
        state={},
    )

    # Test getting override value
    assert instance.get_config("api_base_url") == "https://api.github.com"

    # Test getting default value
    assert instance.get_config("timeout", 30) == 30

    # Test getting None
    assert instance.get_config("nonexistent") is None
