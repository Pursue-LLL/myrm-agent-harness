"""Tally of the model calls one wiki maintenance run makes.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::BaseMessage (POS: LangChain message type)

[OUTPUT]
- AiCallTally: counts the model calls asked and left unanswered; `unavailable` when the model answered none

[POS]
A full run asks the model about up to 25 pages, and a page whose call fails is logged and skipped, so a run
without a working model (no provider configured, key revoked, provider down) finishes like any other.
The tally lets the host tell that run apart from one where the model had nothing to improve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage


@dataclass(slots=True)
class AiCallTally:
    """How many model calls a run asked, and how many of them raised."""

    asked: int = 0
    unanswered: int = 0

    @property
    def unavailable(self) -> bool:
        """The model was asked and answered nothing."""
        return self.asked > 0 and self.unanswered == self.asked

    async def ask(self, llm: BaseChatModel, messages: list[BaseMessage]) -> BaseMessage:
        """``llm.ainvoke`` that counts the call; a failure is counted and raised again.

        Cancellation is a ``BaseException`` and passes through uncounted: stopping a run says nothing
        about the model.
        """
        self.asked += 1
        try:
            return await llm.ainvoke(messages)
        except Exception:
            self.unanswered += 1
            raise
