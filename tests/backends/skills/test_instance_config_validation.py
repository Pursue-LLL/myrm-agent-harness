"""Tests for SkillInstanceConfig validation.

Tests the validation logic in SkillInstanceConfig.__post_init__,
ensuring proper error handling for invalid configurations.
"""

from datetime import datetime

import pytest

from myrm_agent_harness.backends.skills.types import SkillInstanceConfig


def test_valid_instance_config() -> None:
    """Test creating a valid instance config."""
    config = SkillInstanceConfig(
        instance_name="personal",
        skill_name="github_skill",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        env_overrides={"GITHUB_TOKEN": "ghp_xxx"},
        config_overrides={"timeout": 30},
    )

    assert config.instance_name == "personal"
    assert config.skill_name == "github_skill"


def test_instance_name_validation() -> None:
    """Test instance_name validation."""
    now = datetime.now()

    # Empty instance_name
    with pytest.raises(ValueError, match="instance_name must be a non-empty string"):
        SkillInstanceConfig(
            instance_name="",
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
        )

    # Whitespace in instance_name
    with pytest.raises(ValueError, match="cannot contain leading/trailing whitespace"):
        SkillInstanceConfig(
            instance_name=" personal ",
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
        )

    # Invalid characters
    with pytest.raises(ValueError, match="must contain only alphanumeric characters"):
        SkillInstanceConfig(
            instance_name="personal.config",
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
        )

    # Valid names
    for name in ["personal", "work-prod", "server_1", "prod-2024"]:
        config = SkillInstanceConfig(
            instance_name=name,
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
        )
        assert config.instance_name == name


def test_skill_name_validation() -> None:
    """Test skill_name validation."""
    now = datetime.now()

    # Empty skill_name
    with pytest.raises(ValueError, match="skill_name must be a non-empty string"):
        SkillInstanceConfig(
            instance_name="personal",
            skill_name="",
            created_at=now,
            updated_at=now,
        )


def test_env_overrides_validation() -> None:
    """Test env_overrides validation."""
    now = datetime.now()

    # Empty key
    with pytest.raises(ValueError, match="env_overrides key must be non-empty string"):
        SkillInstanceConfig(
            instance_name="personal",
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
            env_overrides={"": "value"},
        )

    # Non-string value
    with pytest.raises(ValueError, match="env_overrides value must be string"):
        SkillInstanceConfig(
            instance_name="personal",
            skill_name="github_skill",
            created_at=now,
            updated_at=now,
            env_overrides={"KEY": 123},  # type: ignore
        )

    # Valid env_overrides
    config = SkillInstanceConfig(
        instance_name="personal",
        skill_name="github_skill",
        created_at=now,
        updated_at=now,
        env_overrides={"GITHUB_TOKEN": "ghp_xxx", "ORG": "my-org"},
    )
    assert config.env_overrides == {"GITHUB_TOKEN": "ghp_xxx", "ORG": "my-org"}


def test_config_overrides_validation() -> None:
    """Test config_overrides validation."""
    now = datetime.now()

    # Valid config_overrides (any JSON-serializable type)
    config = SkillInstanceConfig(
        instance_name="personal",
        skill_name="github_skill",
        created_at=now,
        updated_at=now,
        config_overrides={
            "timeout": 30,
            "api_base_url": "https://api.github.com",
            "enabled": True,
            "tags": ["tag1", "tag2"],
        },
    )
    assert config.config_overrides["timeout"] == 30
    assert config.config_overrides["enabled"] is True
