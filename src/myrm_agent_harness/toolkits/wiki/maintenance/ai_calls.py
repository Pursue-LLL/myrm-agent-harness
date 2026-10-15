"""The model calls of one wiki maintenance run: counted, and stoppable.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::BaseMessage (POS: LangChain message type)

[OUTPUT]
- AiCalls: counts the model calls asked and left unanswered (`unavailable` when the model answered none) and
  ends the run's model phases when the host sets its stop event (`stopped`)
- MaintainStoppedError: raised by `AiCalls.ask` when the run was asked to stop

[POS]
A full run asks the model about up to 25 pages, and a page whose call fails is logged and skipped, so a run
without a working model (no provider configured, key revoked, provider down) finishes like any other; the
count lets the host tell that run apart from one where the model had nothing to improve.
A run takes minutes, so the host can also stop it: the call in flight is abandoned and no further call is
made, while everything already written stays and the run finishes through its normal path. Stopping only
ever ends a model call, never a write: the pages improved so far are intact and indexed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage


class MaintainStoppedError(Exception):
    """The host asked the run to stop; no model call is made or waited for any more."""


def _discard_outcome(task: asyncio.Future[BaseMessage]) -> None:
    """The result of an abandoned call is of no interest; reading it keeps the event loop from logging it."""
    if not task.cancelled():
        task.exception()


@dataclass(slots=True)
class AiCalls:
    """One run's model calls: how many were asked and raised, and whether the host stopped the run."""

    stop: asyncio.Event | None = None
    asked: int = 0
    unanswered: int = 0
    stopped: bool = False

    @property
    def unavailable(self) -> bool:
        """The model was asked and answered nothing."""
        return self.asked > 0 and self.unanswered == self.asked

    async def ask(self, llm: BaseChatModel, messages: list[BaseMessage]) -> BaseMessage:
        """``llm.ainvoke`` that counts the call; a failure is counted and raised again.

        Raises ``MaintainStoppedError`` when the run is asked to stop before or during the call; that call is not
        counted. Cancellation is a ``BaseException`` and passes through uncounted: cancelling a run says
        nothing about the model.
        """
        if self.stop is not None and self.stop.is_set():
            self.stopped = True
            raise MaintainStoppedError
        self.asked += 1
        try:
            if self.stop is None:
                return await llm.ainvoke(messages)
            return await self._until_stopped(llm.ainvoke(messages), self.stop)
        except MaintainStoppedError:
            self.asked -= 1
            self.stopped = True
            raise
        except Exception:
            self.unanswered += 1
            raise

    @staticmethod
    async def _until_stopped(call: Awaitable[BaseMessage], stop: asyncio.Event) -> BaseMessage:
        task = asyncio.ensure_future(call)
        stop_wait = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({task, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
            if not task.done():
                raise MaintainStoppedError
            return task.result()
        finally:
            stop_wait.cancel()
            if not task.done():
                task.cancel()
                task.add_done_callback(_discard_outcome)
