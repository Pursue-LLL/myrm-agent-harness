"""SkillAgent.allows_background_memory_extraction: auto-extraction switch AND memory policy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.skill_agent import SkillAgent


def _allows(*, switch: bool, manager: MagicMock | None) -> bool:
    host = SimpleNamespace(_enable_memory_auto_extraction=switch, memory_manager=manager)
    return SkillAgent.allows_background_memory_extraction(host)  # type: ignore[arg-type]


def _manager(*, allow_l3_extraction: bool) -> MagicMock:
    manager = MagicMock()
    manager.policy.allow_l3_extraction = allow_l3_extraction
    return manager


@pytest.mark.parametrize(
    ("switch", "allow_l3_extraction", "expected"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
    ],
)
def test_requires_both_switch_and_policy(switch: bool, allow_l3_extraction: bool, expected: bool) -> None:
    assert _allows(switch=switch, manager=_manager(allow_l3_extraction=allow_l3_extraction)) is expected


def test_without_memory_manager_only_the_switch_decides() -> None:
    assert _allows(switch=True, manager=None) is True
    assert _allows(switch=False, manager=None) is False
