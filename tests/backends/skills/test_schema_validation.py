"""Tests for _validate_config_overrides schema validation logic."""

import pytest

from myrm_agent_harness.backends.skills.state_manager import _validate_config_overrides

SAMPLE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "api_key": {"type": "string", "format": "password"},
        "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30},
        "temperature": {"type": "number", "minimum": 0.0, "maximum": 2.0},
        "enabled": {"type": "boolean", "default": True},
        "model": {"type": "string", "enum": ["gpt-4", "gpt-3.5", "claude"]},
    },
    "required": ["api_key"],
}


class TestValidateConfigOverrides:
    """Tests for the lightweight JSON Schema validation."""

    def test_valid_config(self) -> None:
        _validate_config_overrides(
            {"api_key": "sk-xxx", "timeout": 60, "enabled": True},
            SAMPLE_SCHEMA,
            "test_skill",
            "default",
        )

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValueError, match="missing required config field 'api_key'"):
            _validate_config_overrides(
                {"timeout": 60},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_wrong_type_string(self) -> None:
        with pytest.raises(ValueError, match="expected string, got int"):
            _validate_config_overrides(
                {"api_key": 12345},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_wrong_type_integer(self) -> None:
        with pytest.raises(ValueError, match="expected integer, got str"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "timeout": "fast"},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_wrong_type_boolean(self) -> None:
        with pytest.raises(ValueError, match="expected boolean, got str"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "enabled": "yes"},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_enum_violation(self) -> None:
        with pytest.raises(ValueError, match="not in allowed values"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "model": "llama"},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_enum_valid(self) -> None:
        _validate_config_overrides(
            {"api_key": "sk-xxx", "model": "claude"},
            SAMPLE_SCHEMA,
            "test_skill",
            "default",
        )

    def test_minimum_violation(self) -> None:
        with pytest.raises(ValueError, match="0 < minimum 1"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "timeout": 0},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_maximum_violation(self) -> None:
        with pytest.raises(ValueError, match="999 > maximum 300"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "timeout": 999},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_number_range_valid(self) -> None:
        _validate_config_overrides(
            {"api_key": "sk-xxx", "temperature": 0.7},
            SAMPLE_SCHEMA,
            "test_skill",
            "default",
        )

    def test_number_minimum_violation(self) -> None:
        with pytest.raises(ValueError, match=r"-0\.1 < minimum 0\.0"):
            _validate_config_overrides(
                {"api_key": "sk-xxx", "temperature": -0.1},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_unknown_property_ignored(self) -> None:
        _validate_config_overrides(
            {"api_key": "sk-xxx", "unknown_field": "value"},
            SAMPLE_SCHEMA,
            "test_skill",
            "default",
        )

    def test_empty_overrides_with_required(self) -> None:
        with pytest.raises(ValueError, match="missing required config field"):
            _validate_config_overrides(
                {},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_no_properties_in_schema(self) -> None:
        _validate_config_overrides(
            {"any": "value"},
            {"type": "object"},
            "test_skill",
            "default",
        )

    def test_multiple_errors(self) -> None:
        with pytest.raises(ValueError, match="config validation failed"):
            _validate_config_overrides(
                {"api_key": 123, "timeout": "slow"},
                SAMPLE_SCHEMA,
                "test_skill",
                "default",
            )

    def test_no_required_field_in_schema(self) -> None:
        schema_no_required: dict[str, object] = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
        _validate_config_overrides({}, schema_no_required, "test_skill", "default")
