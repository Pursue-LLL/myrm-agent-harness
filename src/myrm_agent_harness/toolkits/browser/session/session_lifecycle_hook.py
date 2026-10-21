"""Session lifecycle hook protocol.

[INPUT]
- (none — pure protocol)

[OUTPUT]
- SessionLifecycleHookProtocol: optional hook fired on session save/delete/expire events.

[POS]
Session lifecycle hook protocol. Allows external observers (e.g. the memory system)
to react to encrypted session save/delete/expire events without coupling the browser
toolkit to any specific consumer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionLifecycleHookProtocol(Protocol):
    """Optional observer for browser session persistence events.

    Implementers receive fire-and-forget notifications; exceptions are
    logged but never propagate to the caller.
    """

    async def on_session_saved(self, domain: str, cookie_count: int, local_storage_count: int) -> None:
        """Called after a session is successfully encrypted and stored."""
        ...

    async def on_session_deleted(self, domain: str) -> None:
        """Called after a session is deleted from the vault."""
        ...

    async def on_sessions_expired(self, domains: list[str]) -> None:
        """Called after one or more sessions are removed by TTL cleanup."""
        ...
