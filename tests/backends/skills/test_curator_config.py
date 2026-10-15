"""Tests for CuratorConfig construction-time validation.

A curator sweep runs unattended, so a degenerate threshold must be refused when the
config is built instead of moving the whole skill library in one pass.
"""

from __future__ import annotations

import math

import pytest

from myrm_agent_harness.backends.skills.curator_config import CuratorConfig

_MINIMUMS = [
    ("interval_hours", 1),
    ("stale_after_days", 1),
    ("archive_after_days", 1),
    ("grace_period_days", 0),
    ("max_skills", 1),
    ("min_call_count_for_quality_check", 1),
    ("consolidation_min_skills", 1),
    ("consolidation_min_cluster_size", 2),
]
_RATIOS = ["min_success_rate", "consolidation_similarity_threshold"]


def test_defaults_are_valid_and_survive_a_dict_round_trip() -> None:
    config = CuratorConfig()

    assert CuratorConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize(("field_name", "minimum"), _MINIMUMS)
def test_lower_bound_is_accepted_and_below_it_is_rejected(field_name: str, minimum: int) -> None:
    assert getattr(CuratorConfig(**{field_name: minimum}), field_name) == minimum

    with pytest.raises(ValueError, match=field_name):
        CuratorConfig(**{field_name: minimum - 1})


@pytest.mark.parametrize("field_name", _RATIOS)
@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_ratio_inside_unit_interval_is_accepted(field_name: str, value: float) -> None:
    assert getattr(CuratorConfig(**{field_name: value}), field_name) == value


@pytest.mark.parametrize("field_name", _RATIOS)
@pytest.mark.parametrize("value", [-0.01, 1.01, math.nan, math.inf])
def test_ratio_outside_unit_interval_is_rejected(field_name: str, value: float) -> None:
    with pytest.raises(ValueError, match=field_name):
        CuratorConfig(**{field_name: value})


@pytest.mark.parametrize(
    "data",
    [
        {"max_skills": 0},
        {"max_skills": -3},
        {"stale_after_days": 0},
        {"archive_after_days": 0},
        {"interval_hours": 0},
        {"consolidation_similarity_threshold": 1.5},
    ],
)
def test_from_dict_refuses_degenerate_values(data: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="CuratorConfig"):
        CuratorConfig.from_dict(data)


def test_from_dict_keeps_valid_overrides() -> None:
    config = CuratorConfig.from_dict({"max_skills": 80, "grace_period_days": 0})

    assert config.max_skills == 80
    assert config.grace_period_days == 0
