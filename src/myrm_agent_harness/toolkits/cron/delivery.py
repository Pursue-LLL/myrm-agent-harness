"""Built-in webhook ResultDelivery for cron job results.

Sends an HTTP POST with a JSON payload and HMAC-SHA256 signature.
Retries transient failures with exponential backoff; permanent errors
(ValueError, 4xx) propagate immediately.

Zero application-layer dependencies — uses only framework types and httpx.

[INPUT]
- (none)

[OUTPUT]
- WebhookDelivery: class — Webhook Delivery

[POS]
Built-in webhook ResultDelivery for cron job results.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime

import httpx

from myrm_agent_harness.toolkits.cron.types import CronJob, JobResult

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30
_MAX_RETRIES = 2
_BACKOFF_BASE_S = 2.0


def _is_permanent_error(exc: Exception) -> bool:
    if isinstance(exc, ValueError):
        return True
    if isinstance(exc, RuntimeError):
        return str(exc).startswith("Webhook returned 4")
    return False


class WebhookDelivery:
    """ResultDelivery that POSTs results to a webhook URL with HMAC signing.

    Payload schema::

        {
            "event": "cron.run.completed",
            "job_id": "...",
            "job_name": "...",
            "status": "success" | "error",
            "output": "...",            # truncated to 5000 chars
            "error": "..." | null,      # truncated to 500 chars
            "model": "..." | null,
            "usage": {...} | null,
            "executed_at": "ISO-8601",
            "duration_ms": int | null,
        }

    Security: HMAC-SHA256 signature in ``X-Webhook-Signature`` header,
    keyed by ``job.delivery.secret`` (falls back to ``job.id``).
    """

    def __init__(
        self,
        *,
        connect_timeout: int = _CONNECT_TIMEOUT,
        read_timeout: int = _READ_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
        user_agent: str = "MyrmCron/1.0",
    ) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max_retries
        self._user_agent = user_agent

    async def deliver(self, job: CronJob, result: JobResult) -> None:
        await self._retry(
            lambda: self._post(job, result),
            label=f"webhook:{job.id}",
        )

    async def _post(self, job: CronJob, result: JobResult) -> None:
        url = (job.delivery.target or "").strip()
        if not url:
            raise ValueError(f"Webhook URL missing for job {job.id}")

        payload = {
            "event": "cron.run.completed",
            "job_id": job.id,
            "job_name": job.name,
            "status": "success" if result.success else "error",
            "output": (result.output or "")[:5000],
            "error": result.error[:500] if result.error else None,
            "model": result.metadata.get("model") if result.metadata else None,
            "usage": result.metadata.get("usage") if result.metadata else None,
            "executed_at": datetime.now(UTC).isoformat(),
            "duration_ms": result.metadata.get("duration_ms") if result.metadata else None,
        }

        body = json.dumps(payload, ensure_ascii=False)
        hmac_key = (job.delivery.secret or job.id).encode()
        signature = hmac.new(hmac_key, body.encode(), hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self._user_agent,
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Cron-Job-Id": job.id,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
            follow_redirects=False,
        ) as client:
            from myrm_agent_harness.core.security.http.secure_fetch import secure_request

            resp = await secure_request(
                client,
                "POST",
                url,
                content=body,
                headers=headers,
                timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
            )
            status_code = resp.status_code
            if status_code >= 400:
                raise RuntimeError(f"Webhook returned {status_code}: {resp.text[:200]}")

        logger.debug("Webhook delivered for job %s -> %s (%d)", job.id, url, status_code)

    async def _retry(
        self,
        coro_fn: Callable[[], Coroutine[object, object, None]],
        *,
        label: str = "delivery",
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(1 + self._max_retries):
            try:
                await coro_fn()
                return
            except Exception as exc:
                last_exc = exc
                if _is_permanent_error(exc):
                    raise
                if attempt < self._max_retries:
                    delay = _BACKOFF_BASE_S * (2**attempt)
                    logger.warning(
                        "%s attempt %d/%d failed: %s — retrying in %.1fs",
                        label,
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]
