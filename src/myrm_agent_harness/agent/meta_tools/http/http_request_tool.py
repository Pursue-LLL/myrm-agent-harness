"""HTTP Request Tool for Agent.

Provides a robust HTTP client for the agent to interact with external APIs,
with built-in SSRF protection, retry logic, and error classification.

[INPUT]
- toolkits.network.ssrf_shield::SSRFSecurityError (POS: SSRF (Server-Side Request Forgery) Shield)

[OUTPUT]
- HttpConfig: HTTP request configuration
- HttpRequestInput: Input schema for http_request tool
- http_request: HTTP request with streaming upload and download support
- http_request_tool: Make HTTP requests with streaming upload/download support.

[POS]
HTTP Request Tool for Agent.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.http.client_pool import get_http_client
from myrm_agent_harness.agent.meta_tools.http.error_classifier import classify_http_error, get_user_friendly_message
from myrm_agent_harness.agent.meta_tools.http.retry_policy import (
    DEFAULT_RETRY_POLICY,
    calculate_retry_delay,
    extract_retry_after,
    is_retryable_error,
)
from myrm_agent_harness.toolkits.network.ssrf_shield import SSRFSecurityError, validate_and_resolve_url
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
    """HTTP request with streaming upload and download support

    Args:
        url: Target URL
        method: HTTP method (GET/POST/PUT/DELETE/PATCH)
        headers: Optional headers
        body: Request body (string or bytes)
        files: List of files for multipart upload
               Format: [{"name": "file", "filename": "test.txt", "content": bytes}]
        timeout: Request timeout in seconds (overrides config)
        stream_response: If True, returns AsyncIterator[bytes] for streaming download
        verify_ssl: SSL certificate verification
        config: Optional configuration object

    Returns:
        Response body as string, or AsyncIterator[bytes] if stream_response=True

    Raises:
        httpx.HTTPError: On HTTP errors
        ValueError: On invalid parameters

    Note:
        - Streaming upload: Files are uploaded in chunks (1MB default)
        - Progress callback: Emits progress events via ToolProgressSink
        - Streaming download: For large files (>100MB), use stream_response=True
    """
    cfg = config or _DEFAULT_CONFIG
    timeout_val = timeout or cfg.timeout

    # Validate method
    method = method.upper()
    if method not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
        raise ValueError(f"Unsupported HTTP method: {method}")

    # Apply SSRF Shield (DNS-Resolved)
    enable_ssrf_shield = os.getenv("MYRM_ENABLE_SSRF_SHIELD", "true").lower() in ("true", "1", "yes")
    allowed_hosts_str = os.getenv("MYRM_ALLOWED_INTERNAL_HOSTS", "")
    allowed_hosts = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]

    if enable_ssrf_shield:
        try:
            safe_url, host_header = await validate_and_resolve_url(url, allowed_hosts)
            url = safe_url
            headers = headers or {}
            # Set original Host header for virtual hosting to work with IP-based URL
            if "Host" not in headers and "host" not in headers:
                headers.update(host_header)
        except SSRFSecurityError as e:
            logger.error(f"SSRF attempt blocked: {e}")
            raise ValueError(f"Security Error: {e}") from e

    # Inject Trace ID for distributed tracing (if not already provided)
    headers = headers or {}
    if "X-Trace-ID" not in headers and "x-trace-id" not in headers:
        trace_id = str(uuid.uuid4())
        headers["X-Trace-ID"] = trace_id
        logger.debug(f"Injected X-Trace-ID: {trace_id} for {url}")
    else:
        trace_id = headers.get("X-Trace-ID") or headers.get("x-trace-id")
        logger.debug(f"Using existing X-Trace-ID: {trace_id} for {url}")

    # Enable compression (gzip/deflate) for bandwidth optimization
    # httpx automatically handles compression/decompression
    if "Accept-Encoding" not in headers and "accept-encoding" not in headers:
        headers["Accept-Encoding"] = "gzip, deflate"
        logger.debug(f"Enabled compression (gzip, deflate) for {url}")

    # Inject Idempotency-Key for request deduplication (if provided)
    # This prevents duplicate processing of requests (e.g., payment, order creation)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
        logger.debug(f"Injected Idempotency-Key: {idempotency_key} for {url}")

    # Build request kwargs (verify goes to client, not request)
    request_kwargs = {
        "url": url,
        "method": method,
        "headers": headers,
        "timeout": timeout_val,
    }

    # Handle body
    if body is not None:
        if isinstance(body, str):
            request_kwargs["content"] = body.encode("utf-8")
        else:
            request_kwargs["content"] = body

    # Handle multipart upload
    if files:
        if stream_response:
            raise ValueError("stream_response=True is not supported with file uploads")
        return await _upload_files_with_progress(url, method, headers, files, timeout_val, verify_ssl, cfg)

    # Streaming download (use connection pool with retry)
    if stream_response:

        async def stream_generator():
            client = await get_http_client(verify_ssl)

            # Retry connection (not streaming phase)
            for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
                try:
                    async with client.stream(**request_kwargs) as response:
                        response.raise_for_status()
                        # Once streaming starts, no more retries
                        async for chunk in response.aiter_bytes(chunk_size=cfg.chunk_size_kb * 1024):
                            yield chunk
                    return  # Success, exit
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

    # Regular request (use connection pool with retry)
    client = await get_http_client(verify_ssl)

    from urllib.parse import urljoin

    for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
        try:
            current_kwargs = dict(request_kwargs)
            redirect_count = 0
            max_redirects = 5
            response = None

            while redirect_count <= max_redirects:
                current_kwargs["follow_redirects"] = False

                response = await client.request(**current_kwargs)

                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        break

                    next_url = urljoin(current_kwargs["url"], location)

                    if enable_ssrf_shield:
                        try:
                            safe_url, host_header = await validate_and_resolve_url(next_url, allowed_hosts)
                            current_kwargs["url"] = safe_url

                            headers = dict(current_kwargs.get("headers") or {})
                            headers.update(host_header)
                            current_kwargs["headers"] = headers
                        except SSRFSecurityError as e:
                            logger.error(f"SSRF attempt blocked during redirect: {e}")
                            raise ValueError(f"Security Error during redirect: {e}") from e
                    else:
                        current_kwargs["url"] = next_url

                    if response.status_code in (301, 302, 303) and current_kwargs["method"].upper() != "GET":
                        current_kwargs["method"] = "GET"
                        current_kwargs.pop("content", None)
                        current_kwargs.pop("json", None)
                        current_kwargs.pop("data", None)

                    redirect_count += 1
                    continue

                break

            if response is None:
                raise ValueError("No response received")

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
    """Upload files with progress callback

    Args:
        files: List of file dicts with keys: name, filename, content (bytes or base64 string)

    Returns:
        Response text

    Note:
        Emits progress events via ToolProgressSink:
        {
            "type": "tool_progress",
            "tool": "http_request",
            "progress": {
                "uploaded_bytes": int,
                "total_bytes": int,
                "percent": float,
                "speed_bps": int,
                "eta_seconds": float,
            }
        }
    """
    # Decode and prepare file contents
    file_contents: list[tuple[str, str, bytes]] = []
    for file_dict in files:
        file_name = file_dict["name"]
        filename = file_dict.get("filename", file_name)
        content = file_dict["content"]

        # Decode base64 if string
        if isinstance(content, str):
            try:
                content = base64.b64decode(content)
            except Exception:
                # Not base64, treat as UTF-8 string
                content = content.encode("utf-8")

        file_contents.append((file_name, filename, content))

    # Calculate total size
    total_bytes = sum(len(content) for _, _, content in file_contents)
    uploaded_bytes = [0]  # Use list for closure
    start_time = time.time()

    # Get progress sink
    progress_sink = get_tool_progress_sink()

    # Create progress-reporting file objects
    multipart_files = []
    for file_name, filename, content in file_contents:
        # Wrap content in BytesIO-like object that reports progress
        class ProgressBytesIO:
            """BytesIO wrapper that reports upload progress"""

            def __init__(self, data: bytes):
                self._data = data
                self._pos = 0
                self._size = len(data)

            def read(self, size: int = -1) -> bytes:
                """Read and report progress (sync version for httpx)"""
                if size == -1:
                    chunk = self._data[self._pos :]
                else:
                    chunk = self._data[self._pos : self._pos + size]

                self._pos += len(chunk)
                uploaded_bytes[0] += len(chunk)

                # Emit progress (sync context, need to schedule emit)
                if progress_sink and total_bytes > 0:
                    elapsed = time.time() - start_time
                    percent = (uploaded_bytes[0] / total_bytes) * 100
                    speed_bps = uploaded_bytes[0] / elapsed if elapsed > 0 else 0
                    eta = (total_bytes - uploaded_bytes[0]) / speed_bps if speed_bps > 0 else 0

                    # Schedule emit in event loop
                    try:
                        task = asyncio.create_task(
                            progress_sink.emit(
                                {
                                    "type": "tool_progress",
                                    "tool": "http_request",
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

                        # Log emit failures for observability
                        def _log_emit_error(t):
                            if t.exception():
                                logger.warning(f"Progress emit failed: {t.exception()}")

                        task.add_done_callback(_log_emit_error)
                    except RuntimeError:
                        # No event loop, skip progress
                        pass

                return chunk

            def seek(self, pos: int, whence: int = 0) -> int:
                """Seek to position"""
                if whence == 0:
                    self._pos = pos
                elif whence == 1:
                    self._pos += pos
                elif whence == 2:
                    self._pos = self._size + pos
                return self._pos

            def tell(self) -> int:
                """Current position"""
                return self._pos

        file_obj = ProgressBytesIO(content)
        multipart_files.append((file_name, (filename, file_obj, "application/octet-stream")))

    # Upload with httpx (use connection pool with retry)
    client = await get_http_client(verify_ssl)

    for attempt in range(DEFAULT_RETRY_POLICY.max_retries + 1):
        try:
            # Reset file positions for retry
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


if TYPE_CHECKING:
    pass


class HttpRequestInput(BaseModel):
    """Input schema for http_request tool"""

    url: str = Field(..., description="Target URL (must start with http:// or https://)")
    method: str = Field(default="GET", description="HTTP method (GET/POST/PUT/DELETE/PATCH)")
    headers: dict[str, str] | None = Field(default=None, description="Optional HTTP headers")
    body: str | None = Field(default=None, description="Request body (for POST/PUT/PATCH)")
    files: list[dict] | None = Field(
        default=None, description="Files for multipart upload (format: [{name, filename, content}])"
    )
    timeout: int | None = Field(default=30, description="Request timeout in seconds")
    stream_response: bool = Field(default=False, description="If true, streams response for large downloads")
    verify_ssl: bool = Field(default=True, description="SSL certificate verification")
    idempotency_key: str | None = Field(
        default=None, description="Optional idempotency key for request deduplication (prevents duplicate processing)"
    )


@tool(args_schema=HttpRequestInput)
async def http_request_tool(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    files: list[dict] | None = None,
    timeout: int | None = None,
    stream_response: bool = False,
    verify_ssl: bool = True,
    idempotency_key: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Make HTTP requests with streaming upload/download support.

    Supports:
    - GET/POST/PUT/DELETE/PATCH methods
    - Multipart file upload (with real-time progress)
    - Streaming download (for large files)
    - JSON/Form-data
    - Custom headers

    Examples:
    1. GET request:
       url="https://api.example.com/data", method="GET"

    2. POST JSON:
       url="https://api.example.com/create", method="POST", body='{"key": "value"}', headers={"Content-Type": "application/json"}

    3. Upload file:
       url="https://upload.example.com", method="POST", files=[{"name": "file", "filename": "data.txt", "content": <bytes>}]

    4. Streaming download:
       url="https://download.example.com/model.bin", stream_response=True

    Note: Large file uploads show real-time progress (uploaded_bytes/total_bytes/percent/speed/ETA).
    """
    try:
        result = await http_request(
            url=url,
            method=method,
            headers=headers,
            body=body,
            files=files,
            timeout=timeout,
            stream_response=stream_response,
            verify_ssl=verify_ssl,
            idempotency_key=idempotency_key,
        )

        # Handle streaming download
        if isinstance(result, AsyncIterator):
            chunks = []
            async for chunk in result:
                chunks.append(chunk)
            total_size = sum(len(c) for c in chunks)
            return f"Downloaded {total_size} bytes (streaming download). Content saved to memory."

        from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

        return wrap_with_external_sources_tag(result, source=url)
    except httpx.HTTPError as e:
        category = classify_http_error(e)
        friendly_msg = get_user_friendly_message(category, e)
        logger.error(f"HTTP request failed ({category.value}): {friendly_msg}")
        raise ValueError(friendly_msg) from e
    except Exception as e:
        category = classify_http_error(e)
        friendly_msg = get_user_friendly_message(category, e)
        logger.error(f"HTTP request error ({category.value}): {friendly_msg}")
        raise ValueError(friendly_msg) from e
