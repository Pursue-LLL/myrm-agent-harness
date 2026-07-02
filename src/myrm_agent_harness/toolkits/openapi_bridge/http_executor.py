"""OpenAPI Bridge HTTP Executor.

Executes HTTP requests against OpenAPI endpoints with path parameter substitution,
authentication injection, timeout handling, and retry logic.

[INPUT]
- httpx (POS: async HTTP client)
- .auth::OpenAPIAuthProvider (POS: authentication header resolver)
- .config::OpenAPIServiceConfig (POS: service configuration)

[OUTPUT]
- OpenAPIExecutor: Async HTTP request executor for OpenAPI endpoints

[POS]
OpenAPI Bridge HTTP Executor. Handles the actual HTTP call lifecycle:
path param interpolation → auth injection → request → retry → response parsing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import secure_request
from myrm_agent_harness.infra.tls_compat import create_httpx_client

from .auth import OpenAPIAuthProvider
from .config import AuthConfig

logger = logging.getLogger(__name__)

_PATH_PARAM_PATTERN = re.compile(r"\{(\w+)\}")


class OpenAPIExecutor:
    """Async HTTP executor for OpenAPI endpoint calls.

    Manages an httpx.AsyncClient with configured timeouts and provides
    path parameter substitution, auth header injection, and response parsing.

    Args:
        base_url: API base URL
        auth_config: Authentication configuration
        timeout: Request timeout in seconds
        max_retries: Number of retries on 5xx / network errors
    """

    def __init__(
        self,
        base_url: str,
        auth_config: AuthConfig,
        *,
        service_name: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = OpenAPIAuthProvider(auth_config)
        self._service_name = service_name
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = create_httpx_client(
                timeout=self._timeout,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def execute(
        self,
        method: str,
        path: str,
        *,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Execute an HTTP request against the OpenAPI endpoint.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            path: URL path template (e.g. /users/{user_id})
            path_params: Values to substitute in path template
            query_params: URL query parameters
            body: JSON request body
            headers: Additional request headers

        Returns:
            Response body as string (JSON formatted if possible, raw otherwise)
        """
        resolved_path = self._resolve_path(path, path_params or {})
        url = f"{self._base_url}{resolved_path}"

        auth_headers = await self._auth.get_headers()
        auth_query = self._auth.get_query_params()

        user_auth_headers: dict[str, str] = {}
        from myrm_agent_harness.core.security.types import user_credentials_ctx

        try:
            credentials = user_credentials_ctx.get()
            for cred in credentials:
                if (self._service_name and cred.issuer == self._service_name) or (
                    cred.issuer in self._base_url.lower()
                ):
                    import time

                    token = cred.token
                    if (
                        cred.expires_at is not None
                        and time.time() > cred.expires_at - 300
                        and cred.refresh_callback is not None
                    ):
                        logger.info(
                            "OpenAPIExecutor: Credential for issuer '%s' is expired or expiring soon. Triggering refresh...",
                            cred.issuer,
                        )
                        try:
                            new_cred = await cred.refresh_callback()
                            if new_cred and hasattr(new_cred, "token"):
                                token = new_cred.token
                        except Exception as exc:
                            logger.error(
                                "OpenAPIExecutor: Preemptive refresh callback failed for '%s': %s",
                                cred.issuer,
                                exc,
                            )

                    user_auth_headers["Authorization"] = f"Bearer {token}"
                    logger.info(
                        "OpenAPIExecutor: Injected ephemeral user credentials for issuer '%s'",
                        cred.issuer,
                    )
                    break
        except LookupError:
            pass

        merged_headers = {"Accept": "application/json", **auth_headers}
        if user_auth_headers:
            merged_headers.update(user_auth_headers)
        if headers:
            merged_headers.update(headers)

        merged_query = {**(query_params or {}), **auth_query}

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await secure_request(
                    client,
                    method.upper(),
                    url,
                    params=merged_query or None,
                    json=body,
                    headers=merged_headers,
                    timeout=self._timeout,
                )

                if response.status_code == 401:
                    from myrm_agent_harness.core.security.types import user_credentials_ctx

                    try:
                        credentials = user_credentials_ctx.get()
                        for cred in credentials:
                            if (self._service_name and cred.issuer == self._service_name) or (
                                cred.issuer in self._base_url.lower()
                            ):
                                if cred.refresh_callback is not None:
                                    logger.warning(
                                        "OpenAPIExecutor: Received 401 Unauthorized, triggering refresh callback..."
                                    )
                                    try:
                                        new_cred = await cred.refresh_callback()
                                        if new_cred and hasattr(new_cred, "token"):
                                            merged_headers["Authorization"] = f"Bearer {new_cred.token}"
                                            logger.info(
                                                "OpenAPIExecutor: Retrying 401 request with freshly renewed token"
                                            )
                                            response = await secure_request(
                                                client,
                                                method.upper(),
                                                url,
                                                params=merged_query or None,
                                                json=body,
                                                headers=merged_headers,
                                                timeout=self._timeout,
                                            )
                                            if response.status_code < 500:
                                                return self._format_response(response)
                                    except Exception as exc:
                                        logger.error(
                                            "OpenAPIExecutor: Reactive 401 refresh failed for '%s': %s",
                                            cred.issuer,
                                            exc,
                                        )
                                break
                    except LookupError:
                        pass

                if response.status_code < 500:
                    return self._format_response(response)

                # 5xx: retry
                last_error = httpx.HTTPStatusError(
                    f"Server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
                if attempt < self._max_retries:
                    logger.warning(
                        "OpenAPI request %s %s returned %d, retrying (%d/%d)",
                        method,
                        url,
                        response.status_code,
                        attempt + 1,
                        self._max_retries,
                    )

            except SSRFSecurityError as exc:
                return f"Error: Blocked by SSRF policy: {exc}"
            except httpx.RequestError as e:
                last_error = e
                if attempt < self._max_retries:
                    logger.warning(
                        "OpenAPI request %s %s failed: %s, retrying (%d/%d)",
                        method,
                        url,
                        e,
                        attempt + 1,
                        self._max_retries,
                    )

        return f"Error after {self._max_retries + 1} attempts: {last_error}"

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _resolve_path(path_template: str, params: dict[str, str]) -> str:
        """Substitute path parameters in the URL template."""

        def replacer(match: re.Match[str]) -> str:
            param_name = match.group(1)
            if param_name in params:
                return str(params[param_name])
            return match.group(0)

        return _PATH_PARAM_PATTERN.sub(replacer, path_template)

    @staticmethod
    def _format_response(response: httpx.Response) -> str:
        """Format HTTP response as a human/LLM readable string."""
        status = response.status_code
        content_type = response.headers.get("content-type", "")

        if status == 204:
            return "Success (204 No Content)"

        body = response.text

        # Try to pretty-print JSON responses
        if "json" in content_type or body.strip().startswith(("{", "[")):
            try:
                parsed = json.loads(body)
                # Truncate very large responses
                formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                if len(formatted) > 8000:
                    formatted = formatted[:8000] + "\n... (truncated)"
                if status >= 400:
                    return f"Error {status}: {formatted}"
                return formatted
            except json.JSONDecodeError:
                pass

        # Plain text response
        if len(body) > 4000:
            body = body[:4000] + "\n... (truncated)"

        if status >= 400:
            return f"Error {status}: {body}"
        return body


__all__ = ["OpenAPIExecutor"]
