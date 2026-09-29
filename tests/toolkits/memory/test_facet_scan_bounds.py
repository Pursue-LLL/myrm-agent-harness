"""Bounds that keep facet detection cheap on adversarial text.

Both caps exist so a note that repeats one trigger thousands of times cannot turn
detection into a walk over the whole string.
"""

import pytest

from myrm_agent_harness.toolkits.memory.strategies.merger import (
    DeterministicThreeStateMerger,
)

M = DeterministicThreeStateMerger

TRIGGER = "居住" + "在"


@pytest.fixture
def merger() -> M:
    return DeterministicThreeStateMerger()


def test_occurrence_cap_bounds_repeated_triggers(merger: M) -> None:
    dense = (TRIGGER + "杭州，") * 5_000

    values = merger._extract_facet_values(dense, TRIGGER)

    assert values == frozenset({"杭州"})


def test_value_cap_bounds_distinct_values(merger: M) -> None:
    text = TRIGGER + "杭州，" + TRIGGER + "上海，" + TRIGGER + "北京，" + TRIGGER + "深圳，" + TRIGGER + "广州"

    values = merger._facet_values(text, merger._MUTUALLY_EXCLUSIVE_FACETS["location"])

    assert len(values) == merger._FACET_VALUE_MAX_VALUES
    assert "杭州" in values
