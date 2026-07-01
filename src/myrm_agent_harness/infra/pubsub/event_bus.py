"""
@input: 无外部依赖，纯 asyncio 基础设施
@output: 对外提供通用 PubSubBus（per-subscriber Queue + topic backlog + 幂等去重 + 背压驱逐）
@pos: 框架级进程内发布/订阅引擎

🔄 更新规则：修改此文件后，请更新头注释 + 所属文件夹 _ARCH.md
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections import deque
from typing import Protocol, TypeVar, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class PubSubEventProtocol(Protocol):
    """Minimal contract for events flowing through PubSubBus."""

    @property
    def event_type(self) -> str: ...

    @property
    def data(self) -> dict[str, object]: ...


E = TypeVar("E", bound=PubSubEventProtocol)


def _default_idempotency_key(event: PubSubEventProtocol) -> str:
    """Derive a dedup key from event type and serialised data payload."""
    payload = json.dumps(event.data, sort_keys=True, default=str)
    digest = hashlib.blake2b(payload.encode(), digest_size=8).hexdigest()
    return f"{event.event_type}:{digest}"


class PubSubBus[E: PubSubEventProtocol]:
    """Fan-out event bus backed by per-subscriber asyncio.Queue.

    Supports topic-scoped backlogs (deque, O(1) eviction) and consecutive
    duplicate suppression per topic.

    Generic over event type E which must satisfy PubSubEventProtocol.
    """

    def __init__(self, max_backlog: int = 100) -> None:
        self._subscribers: dict[str | None, list[asyncio.Queue[E]]] = {}
        self._backlogs: dict[str | None, deque[E]] = {}
        self._max_backlog = max_backlog
        self._last_event_key: dict[str | None, str] = {}

    def subscribe(self, topic: str | None = None) -> asyncio.Queue[E]:
        q: asyncio.Queue[E] = asyncio.Queue(maxsize=1024)
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(q)

        # Replay backlog to new subscriber
        if topic in self._backlogs:
            for event in self._backlogs[topic]:
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(event)

        logger.info(
            "PubSubBus: new subscriber on topic %s (total on topic=%d)",
            topic,
            len(self._subscribers[topic]),
        )
        return q

    def unsubscribe(self, q: asyncio.Queue[E], topic: str | None = None) -> None:
        if topic in self._subscribers:
            try:
                self._subscribers[topic].remove(q)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
                logger.info("PubSubBus: subscriber removed on topic %s", topic)
            except ValueError:
                pass

    def publish(self, event: E, topic: str | None = None) -> None:
        # Consecutive duplicate suppression
        key = _default_idempotency_key(event)
        if self._last_event_key.get(topic) == key:
            logger.debug("PubSubBus: suppressed duplicate event on topic %s", topic)
            return
        self._last_event_key[topic] = key

        # Update backlog (deque with maxlen handles eviction automatically)
        if topic not in self._backlogs:
            self._backlogs[topic] = deque(maxlen=self._max_backlog)
        self._backlogs[topic].append(event)

        targets = self._subscribers.get(topic, [])
        if not targets:
            return

        dead: list[asyncio.Queue[E]] = []
        for q in list(targets):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
                logger.warning("PubSubBus: dropping slow subscriber on topic %s", topic)
            except Exception as e:
                dead.append(q)
                logger.warning("PubSubBus: dropping invalid subscriber: %s", e)
        for q in dead:
            self.unsubscribe(q, topic)
