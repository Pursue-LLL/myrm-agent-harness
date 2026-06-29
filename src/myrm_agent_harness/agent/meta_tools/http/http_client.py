"""Internal HTTP client for harness meta-tools (not an Agent tool).

Used by `concurrent_download` and similar internal callers. SSRF shield,
retry logic, and streaming upload/download live here — not exposed to the LLM.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from myrm_agent_harness.agent.meta_tools.http.client_pool import get_http_client
from myrm_agent_harness.agent.meta_tools.http.retry_policy import (
    DEFAULT_RETRY_POLICY,
    calculate_retry_delay,
    extract_retry_after,
    is_retryable_error,
)
from myrm_agent_harness.core.security.http.secure_fetch import (
    is_ssrf_shield_enabled,
    parse_allowed_internal_hosts,
    resolve_secure_http_target,
    secure_request,
)
from myrm_agent_harness.utils.progress_sink import get_tool_progress_sink

logger = logging.getLogger(__name__)

MB = 1024 * 1024


@dataclass
class HttpConfig:
    """HTTP request configuration"""

    timeout: int = 30  # seconds
    max_size_mb: int = 1024  # 1GB
    chunk_size_kb: int = 1024  # 1MB chunks for upload
    retry_count: int = 2
    retry_delay: float = 1.0  # seconds
    verify_ssl: bool = True


_DEFAULT_CONFIG = HttpConfig()


async def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    files: list[dict] | None = None,
    timeout: int | None = None,
    stream_response: bool = False,
    verify_ssl: bool = True,
    idempotency_key: str | None = None,
    config: HttpConfig | None = None,
) -> str | AsyncIterator[bytes]:
    """HTTP request with streaming upload and download support."""
    cfg = config or _DEFAULT_CONFIG
    timeout_val = timeout or cfg.timeout

    method = method.upper()
    if method not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
        raise ValueError(f"Unsupported HTTP method: {method}")

    enable_ssrf_shield = is_ssrf_shield_enabled()
    allowed_hosts = parse_allowed_internal_hosts()

    headers = headers or {}
    if "X-Trace-ID" not in headers and "x-trace-id" not in headers:
        trace_id = str(uuid.uuid4())
        headers["X-Trace-ID"] = trace_id
        logger.debug(f"Injected X-Trace-ID: {trace_id} for {url}")
    else:
        trace_id = headers.get("X-Trace-ID") or headers.get("x-trace-id")
        logger.debug(f"Using existing X-Trace-ID: {trace_id} for {url}")

    if "Accept-Encoding" not in headers and "accept-encoding" not in headers:
        headers["Accept-Encoding"] = "gzip, deflate"
        logger.debug(f"Enabled compression (gzip, deflate) for {url}")

    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
        logger.debug(f"Injected Idempotency-Key: {idempotency_key} for {url}")

    request_kwargs = {
        "url": url,
        "method": method,
        "headers": headers,
        "timeout": timeout_val,
    }

    if body is not None:
        if isinstance(body, str):
            request_kwargs["content"] = body.encode("utf-8")
        else:
            request_kwargs["content"] = body

    if files:
        if stream_response:
            raise ValueError("stream_response=True is not supported with file uploads")
        return await _upload_files_with_progress(url, method, headers, files, timeout_val, verify_ssl, cfg)

    if stream_response:

        async def stream_generator():
            client = await get_http_client(verify_ssl)

            for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
                try:
                    stream_url = url
                    stream_headers = headers
                    if enable_ssrf_shield:
                        target = await resolve_secure_http_target(
                            client,
                            url,
                            method=method,
                            headers=headers,
                            allowed_internal_hosts=allowed_hosts,
                        )
                        stream_url = target.request_url
                        stream_headers = target.headers

                    async with client.stream(
                        method,
                        stream_url,
                        headers=stream_headers,
                        content=request_kwargs.get("content"),
                        timeout=timeout_val,
                        follow_redirects=False,
                    ) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=cfg.chunk_size_kb * 1024):
                            yield chunk
                    return
                except Exception as e:
                    if attempt < DEFAULT_RETRY_POLICY.max_retries and is_retryable_error(e, DEFAULT_RETRY_POLICY):
                        retry_after = extract_retry_after(e)
                        delay = calculate_retry_delay(attempt + 1, DEFAULT_RETRY_POLICY, retry_after=retry_after)
                        logger.warning(
                            f"Streaming download connection failed (attempt {attempt + 1}/{DEFAULT_RETRY_POLICY.max_retries + 1}), "
                            f"retrying in {delay:.2f}s{' (Retry-After)' if retry_after else ''}: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

        return stream_generator()

    client = await get_http_client(verify_ssl)

    for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
        try:
            if enable_ssrf_shield:
                response = await secure_request(
                    client,
                    method,
                    url,
                    headers=headers,
                    content=request_kwargs.get("content"),
                    timeout=timeout_val,
                    allowed_internal_hosts=allowed_hosts,
                    enable_ssrf_shield=True,
                )
                response.raise_for_status()
                return response.text

            response = await client.request(**request_kwargs, follow_redirects=True)
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt < DEFAULT_RETRY_POLICY.max_retries and is_retryable_error(e, DEFAULT_RETRY_POLICY):
                retry_after = extract_retry_after(e)
                delay = calculate_retry_delay(attempt + 1, DEFAULT_RETRY_POLICY, retry_after=retry_after)
                logger.warning(
                    f"HTTP request failed (attempt {attempt + 1}/{DEFAULT_RETRY_POLICY.max_retries + 1}), "
                    f"retrying in {delay:.2f}s{' (Retry-After)' if retry_after else ''}: {e}"
                )
                await asyncio.sleep(delay)
            else:
                raise


async def _upload_files_with_progress(
    url: str,
    method: str,
    headers: dict[str, str] | None,
    files: list[dict],
    timeout: int,
    verify_ssl: bool,
    config: HttpConfig,
) -> str:
    """Upload files with progress callback."""
    file_contents: list[tuple[str, str, bytes]] = []
    for file_dict in files:
        file_name = file_dict["name"]
        filename = file_dict.get("filename", file_name)
        content = file_dict["content"]

        if isinstance(content, str):
            try:
                content = base64.b64decode(content)
            except Exception:
                content = content.encode("utf-8")

        file_contents.append((file_name, filename, content))

    total_bytes = sum(len(content) for _, _, content in file_contents)
    uploaded_bytes = [0]
    start_time = time.time()

    progress_sink = get_tool_progress_sink()

    multipart_files = []
    for file_name, filename, content in file_contents:

        class ProgressBytesIO:
            def __init__(self, data: bytes):
                self._data = data
                self._pos = 0
                self._size = len(data)

            def read(self, size: int = -1) -> bytes:
                if size == -1:
                    chunk = self._data[self._pos :]
                else:
                    chunk = self._data[self._pos : self._pos + size]

                self._pos += len(chunk)
                uploaded_bytes[0] += len(chunk)

                if progress_sink and total_bytes > 0:
                    elapsed = time.time() - start_time
                    percent = (uploaded_bytes[0] / total_bytes) * 100
                    speed_bps = uploaded_bytes[0] / elapsed if elapsed > 0 else 0
                    eta = (total_bytes - uploaded_bytes[0]) / speed_bps if speed_bps > 0 else 0

                    try:
                        task = asyncio.create_task(
                            progress_sink.emit(
                                {
                                    "type": "tool_progress",
                                    "tool": "http_client",
                                    "progress": {
                                        "uploaded_bytes": uploaded_bytes[0],
                                        "total_bytes": total_bytes,
                                        "percent": round(percent, 1),
                                        "speed_bps": int(speed_bps),
                                        "eta_seconds": round(eta, 1),
                                    },
                                }
                            )
                        )

                        def _log_emit_error(t):
                            if t.exception():
                                logger.warning(f"Progress emit failed: {t.exception()}")

                        task.add_done_callback(_log_emit_error)
                    except RuntimeError:
                        pass

                return chunk

            def seek(self, pos: int, whence: int = 0) -> int:
                if whence == 0:
                    self._pos = pos
                elif whence == 1:
                    self._pos += pos
                elif whence == 2:
                    self._pos = self._size + pos
                return self._pos

            def tell(self) -> int:
                return self._pos

        file_obj = ProgressBytesIO(content)
        multipart_files.append((file_name, (filename, file_obj, "application/octet-stream")))

    client = await get_http_client(verify_ssl)

    for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
        try:
            for _, (_, file_obj, _) in multipart_files:
                if hasattr(file_obj, "seek"):
                    file_obj.seek(0)

            response = await client.request(
                method=method, url=url, headers=headers or {}, files=multipart_files, timeout=timeout
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt < DEFAULT_RETRY_POLICY.max_retries and is_retryable_error(e, DEFAULT_RETRY_POLICY):
                retry_after = extract_retry_after(e)
                delay = calculate_retry_delay(attempt + 1, DEFAULT_RETRY_POLICY, retry_after=retry_after)
                logger.warning(
                    f"Multipart upload failed (attempt {attempt + 1}/{DEFAULT_RETRY_POLICY.max_retries + 1}), "
                    f"retrying in {delay:.2f}s{' (Retry-After)' if retry_after else ''}: {e}"
                )
                await asyncio.sleep(delay)
            else:
                raise
