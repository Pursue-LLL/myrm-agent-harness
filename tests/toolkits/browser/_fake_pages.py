"""Page doubles whose protocol commands answer, fail or hang forever, as on a wedged page.

[OUTPUT]
- FakeCdp / FakeContext / FakePage: minimal Patchright-shaped doubles with switchable behaviour

[POS]
A main frame stuck in a stalled navigation or a spinning renderer leaves page-level commands
(`evaluate`, `close`, ...) pending with no timeout of their own. Unit tests of the bounded
page-health and tab-recovery code need that behaviour without a browser; real-browser
counterparts live in the integration tests.
"""

from __future__ import annotations

import asyncio
from typing import Literal

Mode = Literal["ok", "hang"]
EvaluateMode = Literal["ok", "raise", "hang"]


class FakeCdp:
    """CDP session whose `send` / `detach` can answer or hang forever."""

    def __init__(self, *, send: Mode = "ok", detach: Mode = "ok") -> None:
        self._send = send
        self._detach = detach
        self.sent: list[str] = []
        self.detach_called = False

    async def send(self, method: str) -> None:
        self.sent.append(method)
        if self._send == "hang":
            await asyncio.Event().wait()

    async def detach(self) -> None:
        self.detach_called = True
        if self._detach == "hang":
            await asyncio.Event().wait()


class FakeContext:
    def __init__(self, cdp: FakeCdp | None) -> None:
        self._cdp = cdp

    async def new_cdp_session(self, page: object) -> FakeCdp:
        if self._cdp is None:
            raise RuntimeError("CDP is not supported by this engine")
        return self._cdp


class FakePage:
    """Page double: `evaluate` and `close` behaviour and the open/closed state are switchable."""

    def __init__(
        self,
        *,
        cdp: FakeCdp | None = None,
        evaluate: EvaluateMode = "ok",
        close: Mode = "ok",
        closed: bool = False,
        url: str = "about:blank",
    ) -> None:
        self.context = FakeContext(cdp)
        self.evaluate_mode = evaluate
        self.close_mode = close
        self.closed = closed
        self.url = url
        self.evaluated: list[str] = []
        self.close_calls = 0

    def is_closed(self) -> bool:
        return self.closed

    async def evaluate(self, expression: str) -> int:
        self.evaluated.append(expression)
        if self.closed:
            raise RuntimeError("Target page, context or browser has been closed")
        if self.evaluate_mode == "raise":
            raise RuntimeError("Execution context was destroyed")
        if self.evaluate_mode == "hang":
            await asyncio.Event().wait()
        return 1

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_mode == "hang":
            await asyncio.Event().wait()
        self.closed = True

    async def bring_to_front(self) -> None:
        return None

    def on(self, *_args: object) -> None:
        return None

    def off(self, *_args: object) -> None:
        return None

    def remove_listener(self, *_args: object) -> None:
        return None
