"""Interrupt identity — the id an approval card carries, and the pause of the task it names

[INPUT]
- langgraph.types::Command (POS: resume 指令)

[OUTPUT]
- is_interrupt_id: whether a string has the shape of a LangGraph interrupt id
- encode_interrupt_id / decode_interrupt_id: the card id ``<langgraph interrupt id>.<round>``
- AddressedResume: a resume ``Command`` that also carries the round every pending interrupt announces itself at
- announced_rounds: the rounds the stream dispatcher stamps on the interrupts a run announces

[POS]
LangGraph's interrupt id names the task that paused, not the pause. A task that calls ``interrupt()`` several times in a
row (a delegation that asks for approval before every step) therefore announces each of its pauses under one id. Used
as the card id, it would make the second pause look like an echo of the first card (the client drops it) and would let
an answer to the first card be taken for the answer to the second.

The card id adds the round: how many answers that task has already consumed. Each pause of a task gets its own id, a
card answered earlier can never be mistaken for a later one, and the round never needs a counter of its own because the
checkpoint already holds it.

The rounds are read once, at the resume choke point (``_internals/resume_addressing.py``), before the run starts and
while no write is in flight, then travel on ``AddressedResume`` to the dispatcher. Reading the checkpoint while the run
is announcing would race with the writes of the very pause being announced.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from langgraph.types import Command

_INTERRUPT_ID = r"[0-9a-f]{32}"
_INTERRUPT_ID_PATTERN = re.compile(_INTERRUPT_ID)
_CARD_ID_PATTERN = re.compile(rf"(?P<interrupt_id>{_INTERRUPT_ID})\.(?P<round>0|[1-9][0-9]{{0,5}})")


class CardId(NamedTuple):
    """The two halves of a card id."""

    interrupt_id: str
    round: int


# LangGraph declares ``Command`` frozen through dynamic dataclass options mypy cannot see; a subclass must be frozen too.
@dataclass(frozen=True, kw_only=True, slots=True)
class AddressedResume(Command[object]):  # type: ignore[misc]
    """A resume command that knows the round each interrupt pending at resume time announces itself at.

    ``announce_rounds`` maps a pending interrupt id to the answers its task will have consumed once this resume ran:
    one more than before for the interrupt the command answers, unchanged for every other one.
    """

    announce_rounds: Mapping[str, int]


def is_interrupt_id(value: object) -> bool:
    """Whether ``value`` has the shape LangGraph requires of an interrupt id inside a resume map."""
    return isinstance(value, str) and _INTERRUPT_ID_PATTERN.fullmatch(value) is not None


def encode_interrupt_id(interrupt_id: str, round_: int) -> str:
    """The card id of the pause ``round_`` of the task LangGraph names ``interrupt_id``."""
    return f"{interrupt_id}.{round_}"


def decode_interrupt_id(card_id: object) -> CardId | None:
    """The halves of a card id; ``None`` for anything this module did not produce."""
    if not isinstance(card_id, str) or (match := _CARD_ID_PATTERN.fullmatch(card_id)) is None:
        return None
    return CardId(match["interrupt_id"], int(match["round"]))


def announced_rounds(agent_input: object) -> Mapping[str, int] | None:
    """The rounds to stamp on the interrupts a run announces; ``None`` when they are unknown.

    A fresh run starts every task at round 0. A resume is only known when it went through ``address_resume_to_pending``;
    any other command leaves the pauses without a card id rather than guessing one.
    """
    if isinstance(agent_input, AddressedResume):
        return agent_input.announce_rounds
    return None if isinstance(agent_input, Command) else {}
