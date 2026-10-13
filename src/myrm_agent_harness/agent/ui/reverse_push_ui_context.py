"""Reverse Push Extension UI Context Implementation.

[INPUT]
- ExtensionUIContext from .base_ui_context
- UIRequest, UIResponse, UISelectOption, UINotifyLevel, ExtensionUIError, ExtensionUITimeoutError, ExtensionUICancelledError from .ui_types

[OUTPUT]
- ReversePushUIContext

[POS]
Bi-directional reverse push interaction driver for WebUI, Desktop, and RPC channels.
Dispatches UIRequest frames over push_sink, holds execution via asyncio.Future, and resolves on UIResponse frames.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

from .base_ui_context import ExtensionUIContext
from .ui_types import (
    ExtensionUICancelledError,
    ExtensionUIError,
    ExtensionUITimeoutError,
    UINotifyLevel,
    UIRequest,
    UIResponse,
    UISelectOption,
)

logger = logging.getLogger(__name__)

PushSink = Callable[[UIRequest], Awaitable[None]]


class ReversePushUIContext(ExtensionUIContext):
    """Bi-directional reverse push driver holding execution until client responds."""

    def __init__(self, push_sink: PushSink) -> None:
        self._push_sink = push_sink
        self._pending_requests: dict[str, asyncio.Future[UIResponse]] = {}
        self._lock = asyncio.Lock()

    @property
    def pending_count(self) -> int:
        """Returns the number of active requests awaiting user response."""
        return len(self._pending_requests)

    def is_pending(self, request_id: str) -> bool:
        """Checks if a request is currently pending."""
        return request_id in self._pending_requests

    async def resolve_response(self, response: UIResponse) -> bool:
        """Resolves a pending UI request with an incoming client UIResponse frame."""
        async with self._lock:
            future = self._pending_requests.get(response.request_id)
            if future is None or future.done():
                logger.warning(
                    "[ReversePushUIContext] Received response for non-existent or completed request: %s",
                    response.request_id,
                )
                return False

            future.set_result(response)
            return True

    async def cancel_request(self, request_id: str, reason: str = "Interaction cancelled by operator") -> bool:
        """Cancels a pending request with a cancellation response."""
        cancel_response = UIResponse(request_id=request_id, cancelled=True, error=reason)
        return await self.resolve_response(cancel_response)

    async def _execute_interactive_request(self, request: UIRequest) -> UIResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[UIResponse] = loop.create_future()

        async with self._lock:
            self._pending_requests[request.request_id] = future

        try:
            await self._push_sink(request)
            response = await asyncio.wait_for(future, timeout=request.timeout_s)
        except TimeoutError as err:
            logger.warning(
                "[ReversePushUIContext] UI request %s ('%s') timed out after %.1fs",
                request.request_id,
                request.title,
                request.timeout_s,
            )
            raise ExtensionUITimeoutError(
                f"Interaction '{request.title}' timed out after {request.timeout_s}s"
            ) from err
        finally:
            async with self._lock:
                self._pending_requests.pop(request.request_id, None)

        if response.cancelled:
            logger.info("[ReversePushUIContext] User cancelled interaction %s", request.request_id)
            raise ExtensionUICancelledError(response.error or "User cancelled interaction")

        if response.error:
            logger.error("[ReversePushUIContext] Interaction %s returned error: %s", request.request_id, response.error)
            raise ExtensionUIError(response.error)

        return response

    async def select(
        self,
        title: str,
        options: Sequence[UISelectOption],
        default: str | None = None,
        timeout_s: float = 60.0,
    ) -> str:
        req_id = f"uireq_{uuid.uuid4().hex[:12]}"
        request = UIRequest(
            request_id=req_id,
            request_type="select",
            title=title,
            options=tuple(options),
            default_value=default,
            timeout_s=timeout_s,
        )
        response = await self._execute_interactive_request(request)
        if isinstance(response.value, str):
            return response.value
        if default is not None:
            return default
        if options:
            return options[0].value
        return ""

    async def confirm(
        self,
        title: str,
        message: str,
        default: bool = False,
        timeout_s: float = 60.0,
    ) -> bool:
        req_id = f"uireq_{uuid.uuid4().hex[:12]}"
        request = UIRequest(
            request_id=req_id,
            request_type="confirm",
            title=title,
            message=message,
            default_value=default,
            timeout_s=timeout_s,
        )
        response = await self._execute_interactive_request(request)
        if isinstance(response.value, bool):
            return response.value
        return default

    async def input(
        self,
        title: str,
        placeholder: str = "",
        default: str = "",
        timeout_s: float = 60.0,
    ) -> str:
        req_id = f"uireq_{uuid.uuid4().hex[:12]}"
        request = UIRequest(
            request_id=req_id,
            request_type="input",
            title=title,
            placeholder=placeholder,
            default_value=default,
            timeout_s=timeout_s,
        )
        response = await self._execute_interactive_request(request)
        if isinstance(response.value, str):
            return response.value
        return default

    async def editor(
        self,
        title: str,
        content: str,
        language: str = "text",
        timeout_s: float = 300.0,
    ) -> str:
        req_id = f"uireq_{uuid.uuid4().hex[:12]}"
        request = UIRequest(
            request_id=req_id,
            request_type="editor",
            title=title,
            content=content,
            language=language,
            timeout_s=timeout_s,
        )
        response = await self._execute_interactive_request(request)
        if isinstance(response.value, str):
            return response.value
        return content

    async def notify(
        self,
        message: str,
        level: UINotifyLevel = "info",
    ) -> None:
        req_id = f"uireq_{uuid.uuid4().hex[:12]}"
        request = UIRequest(
            request_id=req_id,
            request_type="notify",
            title=message,
            message=level,
            timeout_s=0.0,
        )
        await self._push_sink(request)
