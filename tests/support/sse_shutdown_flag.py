"""Reset sse-starlette's process-global shutdown flag between pytest servers.

[INPUT]
- sse_starlette.sse::AppStatus (POS: process-global uvicorn shutdown signal shared by every EventSourceResponse)

[OUTPUT]
- reset_sse_shutdown_flag: Clear ``AppStatus.should_exit`` after a test uvicorn server exits

[POS]
Harness pytest-only teardown helper. sse-starlette flips ``AppStatus.should_exit``
the first time a uvicorn server in the process exits and never resets it, which
makes every later streamable-http server cancel its SSE responses as if it were
shutting down.
"""

from __future__ import annotations

import asyncio


async def reset_sse_shutdown_flag() -> None:
    """Clear sse-starlette's process-global "shutting down" flag.

    The library flips ``AppStatus.should_exit`` the first time any uvicorn
    server in this process exits and never resets it; every later
    streamable-http server would then cancel its SSE responses as if it were
    shutting down. Wait for the shutdown watcher's last broadcast before
    clearing so the next server in the same pytest process starts clean.
    """
    import sse_starlette.sse as _sse

    app_status = getattr(_sse, "AppStatus", None)
    if app_status is None:
        return

    # The watcher polls every 0.5s and flips the flag right before it
    # broadcasts, so a short poll loop is both faster and safer than a fixed
    # sleep: we clear only after the broadcast has fired.
    for _ in range(10):
        if app_status.should_exit:
            break
        await asyncio.sleep(0.1)
    app_status.should_exit = False
