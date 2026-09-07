"""A2A (Agent-to-Agent) outbound client with SSRF protection.

Enables Myrm agents to securely discover, dispatch, monitor, and cancel tasks
on external A2A-compliant agents using standard JSON-RPC 2.0.

[INPUT]
- peer_url, prompt, bearer_token, timeout_seconds

[OUTPUT]
- A2ATask, task state, artifacts

[POS]
Outbound client communication layer for A2A cross-agent task delegation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Mapping

import httpx

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import secure_request
from myrm_agent_harness.infra.tls_compat import create_httpx_client
from myrm_agent_harness.toolkits.a2a.types import (
    A2ATask,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    TaskStatus,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 60.0
_POLL_INTERVAL_SEC = 1.0


class A2AClientError(Exception):
    """Base exception for A2A client failures."""


class A2ASSRFBlockedError(A2AClientError):
    """Raised when an outbound A2A target URL is blocked by SSRF policy."""


class A2ARpcError(A2AClientError):
    """Raised when the remote A2A node returns a JSON-RPC error."""

    def __init__(self, error: JsonRpcError) -> None:
        super().__init__(f"A2A RPC error {error.code}: {error.message}")
        self.error = error


class A2AClient:
    """Outbound client for communicating with remote A2A agent nodes."""

    def __init__(
        self,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SEC,
        allowed_internal_hosts: list[str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.allowed_internal_hosts = allowed_internal_hosts

    async def _post_json_rpc(
        self,
        endpoint_url: str,
        request: JsonRpcRequest,
        *,
        bearer_token: str | None = None,
        timeout_sec: float | None = None,
    ) -> JsonRpcResponse:
        """Send JSON-RPC request to remote endpoint through SSRF-protected HTTP."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        payload_bytes = json.dumps(request.model_dump(exclude_none=True)).encode(
            "utf-8"
        )
        actual_timeout = timeout_sec or self.timeout_seconds

        try:
            async with create_httpx_client(
                timeout=actual_timeout, follow_redirects=False
            ) as http_client:
                resp = await secure_request(
                    http_client,
                    "POST",
                    endpoint_url,
                    headers=headers,
                    content=payload_bytes,
                    timeout=actual_timeout,
                    allowed_internal_hosts=self.allowed_internal_hosts,
                )
        except SSRFSecurityError as e:
            raise A2ASSRFBlockedError(
                f"A2A request to {endpoint_url} blocked by SSRF: {e}"
            ) from e
        except Exception as e:
            raise A2AClientError(
                f"HTTP transport error contacting {endpoint_url}: {e}"
            ) from e

        if not resp.is_success:
            raise A2AClientError(
                f"HTTP status {resp.status_code} from {endpoint_url}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
            rpc_resp = JsonRpcResponse.model_validate(data)
            if rpc_resp.error is not None:
                raise A2ARpcError(rpc_resp.error)
            return rpc_resp
        except A2ARpcError:
            raise
        except Exception as e:
            raise A2AClientError(
                f"Malformed JSON-RPC response from {endpoint_url}: {e}"
            ) from e

    async def send_task(
        self,
        endpoint_url: str,
        prompt: str,
        *,
        task_id: str | None = None,
        agent_id: str | None = None,
        push_url: str | None = None,
        push_secret: str | None = None,
        bearer_token: str | None = None,
        timeout_sec: float | None = None,
    ) -> A2ATask:
        """Dispatch a new task to a remote A2A agent."""
        params: dict[str, object] = {"prompt": prompt}
        if task_id:
            params["taskId"] = task_id
        if agent_id:
            params["agentId"] = agent_id
        if push_url:
            params["pushUrl"] = push_url
        if push_secret:
            params["pushSecret"] = push_secret

        req = JsonRpcRequest(
            method="tasks/send", params=params, id=f"send-{int(time.time()*1000)}"
        )
        resp = await self._post_json_rpc(
            endpoint_url,
            req,
            bearer_token=bearer_token,
            timeout_sec=timeout_sec,
        )

        if not isinstance(resp.result, dict):
            raise A2AClientError("Expected dictionary in result from tasks/send")
        return A2ATask.model_validate(resp.result)

    async def get_task(
        self,
        endpoint_url: str,
        task_id: str,
        *,
        bearer_token: str | None = None,
        timeout_sec: float | None = None,
    ) -> A2ATask:
        """Fetch current status and artifacts of an A2A task."""
        req = JsonRpcRequest(
            method="tasks/get",
            params={"taskId": task_id},
            id=f"get-{int(time.time()*1000)}",
        )
        resp = await self._post_json_rpc(
            endpoint_url,
            req,
            bearer_token=bearer_token,
            timeout_sec=timeout_sec,
        )

        if not isinstance(resp.result, dict):
            raise A2AClientError("Expected dictionary in result from tasks/get")
        return A2ATask.model_validate(resp.result)

    async def cancel_task(
        self,
        endpoint_url: str,
        task_id: str,
        *,
        bearer_token: str | None = None,
        timeout_sec: float | None = None,
    ) -> bool:
        """Request remote cancellation of an A2A task."""
        req = JsonRpcRequest(
            method="tasks/cancel",
            params={"taskId": task_id},
            id=f"cancel-{int(time.time()*1000)}",
        )
        resp = await self._post_json_rpc(
            endpoint_url,
            req,
            bearer_token=bearer_token,
            timeout_sec=timeout_sec,
        )

        if isinstance(resp.result, dict):
            return bool(resp.result.get("cancelled", True))
        return True

    async def wait_for_completion(
        self,
        endpoint_url: str,
        task_id: str,
        *,
        bearer_token: str | None = None,
        poll_interval_sec: float = _POLL_INTERVAL_SEC,
        max_wait_sec: float = 300.0,
    ) -> A2ATask:
        """Poll remote A2A task until reaching terminal state."""
        start_time = time.monotonic()
        while time.monotonic() - start_time < max_wait_sec:
            task = await self.get_task(endpoint_url, task_id, bearer_token=bearer_token)
            if task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                return task
            await asyncio.sleep(poll_interval_sec)

        raise asyncio.TimeoutError(
            f"A2A task {task_id} did not complete within {max_wait_sec} seconds."
        )
