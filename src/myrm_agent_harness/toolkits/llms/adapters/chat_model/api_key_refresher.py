"""API key refresher: the single hook that lets a host renew an expiring key before an LLM request.

Some credentials outlive neither a long agent run nor a long-lived model instance (subscription OAuth
access tokens expire within the hour). A host registers one refresher; the async generation paths ask
it for a renewed key before each request, so the instance keeps working without rebuilding it and
without the adapter knowing how the credential is issued or renewed.

[INPUT]
- none (pure registry)

[OUTPUT]
- ApiKeyRefresher: the refresher signature, current key in, renewed key (or None) out
- set_api_key_refresher: register the refresher, or None to remove it
- renew_api_key: ask the registered refresher about one key

[POS]
Extension point between the LLM adapter and the credential layers above it; the adapter holds no
credential policy and imports nothing from the host.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

ApiKeyRefresher = Callable[[str], Awaitable[str | None]]

_refresher: ApiKeyRefresher | None = None


def set_api_key_refresher(refresher: ApiKeyRefresher | None) -> None:
    """Register *refresher* for every ChatLiteLLM async request in this process, or remove it with None."""
    global _refresher
    _refresher = refresher


async def renew_api_key(current: str | None) -> str | None:
    """Return a renewed key for *current*, or None when it should be kept.

    A refresher that fails never blocks the request: the current key is used and the provider's own
    rejection, if any, surfaces through the normal error path.
    """
    if _refresher is None or not current:
        return None
    try:
        renewed = await _refresher(current)
    except Exception:
        logger.warning("API key refresher failed; keeping the current key", exc_info=True)
        return None
    return renewed if renewed and renewed != current else None
