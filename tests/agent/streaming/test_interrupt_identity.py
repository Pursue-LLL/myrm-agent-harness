"""Card id format, and the contract with LangGraph that the round is derived from."""

from __future__ import annotations

from dataclasses import replace

import pytest
from langgraph._internal._constants import RESUME
from langgraph.types import Command

from myrm_agent_harness.agent._internals import resume_addressing
from myrm_agent_harness.agent.streaming.interrupt_identity import (
    AddressedResume,
    CardId,
    announced_rounds,
    decode_interrupt_id,
    encode_interrupt_id,
    is_interrupt_id,
)

_ID = "0123456789abcdef0123456789abcdef"


def test_a_card_id_round_trips() -> None:
    assert decode_interrupt_id(encode_interrupt_id(_ID, 7)) == CardId(_ID, 7)
    assert decode_interrupt_id(encode_interrupt_id(_ID, 0)) == CardId(_ID, 0)


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        7,
        "",
        _ID,
        f"{_ID}.",
        f"{_ID}.-1",
        f"{_ID}.01",
        f"{_ID}.1.2",
        f"{_ID}.1234567",
        f" {_ID}.1",
        f"{_ID.upper()}.1",
        f"{_ID[:-1]}.1",
        f"x{_ID}.1",
    ],
)
def test_anything_this_module_did_not_produce_is_not_a_card_id(malformed: object) -> None:
    assert decode_interrupt_id(malformed) is None


def test_an_interrupt_id_is_the_32_hex_shape_langgraph_accepts_in_a_resume_map() -> None:
    assert is_interrupt_id(_ID)
    assert not any(map(is_interrupt_id, [None, "", "abc", f"{_ID}.0", _ID.upper(), _ID + "0"]))


def test_a_fresh_run_starts_every_task_at_round_zero() -> None:
    assert announced_rounds({"messages": []}) == {}


def test_a_resume_that_was_not_addressed_has_no_known_rounds() -> None:
    assert announced_rounds(Command(resume={"answer": "yes"})) is None


def test_an_addressed_resume_is_a_command_that_keeps_its_rounds_when_copied() -> None:
    resume = AddressedResume(resume={"answer": "yes"}, announce_rounds={_ID: 2})

    assert isinstance(resume, Command)
    assert announced_rounds(resume) == {_ID: 2}
    assert announced_rounds(replace(resume, update={"messages": []})) == {_ID: 2}


def test_the_resume_channel_the_round_is_counted_in_is_the_one_langgraph_writes() -> None:
    """A LangGraph release that renames the channel must fail here, not silently report round 0 forever."""
    assert RESUME == resume_addressing.RESUME_CHANNEL
