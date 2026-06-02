from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.agent.security import (
    EphemeralUserCredential,
    user_credentials_ctx,
)
from myrm_agent_harness.agent.security.safe_exec import safe_exec
from myrm_agent_harness.agent.security.types import (
    propagate_user_credentials,
    with_user_credentials,
)
from myrm_agent_harness.toolkits.openapi_bridge import AuthConfig, AuthType
from myrm_agent_harness.toolkits.openapi_bridge.http_executor import OpenAPIExecutor


def test_credentials_context_isolation() -> None:
    """Verify ContextVar-based user credentials isolation across execution threads."""
    assert len(user_credentials_ctx.get()) == 0

    cred1 = EphemeralUserCredential(issuer="github", token="ghp_test1")
    token_ctx = user_credentials_ctx.set((cred1,))
    assert user_credentials_ctx.get() == (cred1,)

    user_credentials_ctx.reset(token_ctx)
    assert len(user_credentials_ctx.get()) == 0


@pytest.mark.asyncio
async def test_safe_exec_credentials_injection() -> None:
    """Verify safe_exec retrieves credentials from ContextVar and injects them as env vars."""
    cred1 = EphemeralUserCredential(issuer="feishu", token="fs_test_token")
    cred2 = EphemeralUserCredential(issuer="github", token="gh_test_token")
    cred3 = EphemeralUserCredential(issuer="custom_service", token="cs_test_token")

    user_credentials_ctx.set((cred1, cred2, cred3))

    # Mock asyncio.create_subprocess_exec to inspect the env parameter passed down
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
        mock_exec.return_value = mock_proc

        await safe_exec("echo hello", env={"EXISTING_VAR": "value"})

        assert mock_exec.call_count == 1
        _, kwargs = mock_exec.call_args
        passed_env = kwargs.get("env")

        assert passed_env is not None
        assert passed_env["EXISTING_VAR"] == "value"
        # Feishu mapping
        assert passed_env["FEISHU_USER_ACCESS_TOKEN"] == "fs_test_token"
        # GitHub mapping
        assert passed_env["GITHUB_TOKEN"] == "gh_test_token"
        # Custom service fallback uppercase mapping
        assert passed_env["CUSTOM_SERVICE_TOKEN"] == "cs_test_token"


@pytest.mark.asyncio
async def test_openapi_executor_credential_injection() -> None:
    """Verify OpenAPIExecutor correctly resolves and injects ContextVar Bearer tokens."""
    cred1 = EphemeralUserCredential(issuer="jira", token="jira_test_token")
    user_credentials_ctx.set((cred1,))

    auth_cfg = AuthConfig(type=AuthType.NONE)
    executor = OpenAPIExecutor(
        base_url="https://api.jira.com", auth_config=auth_cfg, service_name="jira"
    )

    # Mock the httpx client request method
    with patch.object(httpx.AsyncClient, "request") as mock_request:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": "ok"}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_request.return_value = mock_resp

        res = await executor.execute("GET", "/issues/123")

        assert "ok" in res
        assert mock_request.call_count == 1
        kwargs = mock_request.call_args[1]
        headers = kwargs.get("headers")

        assert headers is not None
        assert headers["Authorization"] == "Bearer jira_test_token"


@pytest.mark.asyncio
async def test_openapi_executor_preemptive_refresh() -> None:
    """Verify OpenAPIExecutor preemptively triggers refresh callback on expired/expiring tokens."""
    refreshed_cred = EphemeralUserCredential(
        issuer="github", token="gh_fresh_token", expires_at=time.time() + 3600
    )
    mock_refresh_callback = AsyncMock(return_value=refreshed_cred)

    # Credential expiring in 1 minute (less than 5 minutes threshold)
    expiring_cred = EphemeralUserCredential(
        issuer="github",
        token="gh_old_token",
        expires_at=time.time() + 60,
        refresh_callback=mock_refresh_callback,
    )
    user_credentials_ctx.set((expiring_cred,))

    auth_cfg = AuthConfig(type=AuthType.NONE)
    executor = OpenAPIExecutor(
        base_url="https://api.github.com", auth_config=auth_cfg, service_name="github"
    )

    with patch.object(httpx.AsyncClient, "request") as mock_request:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": "ok"}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_request.return_value = mock_resp

        await executor.execute("GET", "/user")

        assert mock_refresh_callback.call_count == 1
        assert mock_request.call_count == 1
        headers = mock_request.call_args[1].get("headers")
        assert headers is not None
        assert headers["Authorization"] == "Bearer gh_fresh_token"


@pytest.mark.asyncio
async def test_openapi_executor_reactive_401_refresh() -> None:
    """Verify OpenAPIExecutor reactively triggers refresh callback and retries on 401 Unauthorized."""
    refreshed_cred = EphemeralUserCredential(issuer="feishu", token="fs_fresh_token")
    mock_refresh_callback = AsyncMock(return_value=refreshed_cred)

    active_cred = EphemeralUserCredential(
        issuer="feishu",
        token="fs_stale_token",
        expires_at=time.time() + 3600,  # Not expired preemptively
        refresh_callback=mock_refresh_callback,
    )
    user_credentials_ctx.set((active_cred,))

    auth_cfg = AuthConfig(type=AuthType.NONE)
    executor = OpenAPIExecutor(
        base_url="https://api.feishu.cn", auth_config=auth_cfg, service_name="feishu"
    )

    with patch.object(httpx.AsyncClient, "request") as mock_request:
        # First call returns 401, second returns 200
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_resp_401.text = "Unauthorized"
        mock_resp_401.headers = {}

        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.text = "Success"
        mock_resp_200.headers = {}

        # Intercept call_args to capture copies of headers because they are mutated in-place
        headers_history = []

        async def mock_request_side_effect(*args, **kwargs):
            headers_history.append(dict(kwargs.get("headers", {})))
            if len(headers_history) == 1:
                return mock_resp_401
            return mock_resp_200

        mock_request.side_effect = mock_request_side_effect

        res = await executor.execute("GET", "/bitable/v1")

        assert "Success" in res
        assert mock_refresh_callback.call_count == 1
        assert mock_request.call_count == 2

        # Assert correct header histories
        assert headers_history[0]["Authorization"] == "Bearer fs_stale_token"
        assert headers_history[1]["Authorization"] == "Bearer fs_fresh_token"


@pytest.mark.asyncio
async def test_safe_exec_scoped_credential_injection() -> None:
    """Verify safe_exec only injects credentials matching allowed_issuers."""
    cred1 = EphemeralUserCredential(issuer="feishu", token="fs_test_token")
    cred2 = EphemeralUserCredential(issuer="github", token="gh_test_token")

    user_credentials_ctx.set((cred1, cred2))

    # Test injecting only github
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
        mock_exec.return_value = mock_proc

        await safe_exec("echo hello", allowed_issuers=["github"])

        assert mock_exec.call_count == 1
        _, kwargs = mock_exec.call_args
        passed_env = kwargs.get("env")

        assert passed_env is not None
        assert "GITHUB_TOKEN" in passed_env
        assert passed_env["GITHUB_TOKEN"] == "gh_test_token"
        assert "FEISHU_USER_ACCESS_TOKEN" not in passed_env

    # Test injecting empty list (none allowed)
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
        mock_exec.return_value = mock_proc

        await safe_exec("echo hello", allowed_issuers=[])

        assert mock_exec.call_count == 1
        _, kwargs = mock_exec.call_args
        passed_env = kwargs.get("env")

        assert passed_env is not None
        assert "GITHUB_TOKEN" not in passed_env
        assert "FEISHU_USER_ACCESS_TOKEN" not in passed_env

    # Test case-insensitivity and mixed casing
    cred3 = EphemeralUserCredential(issuer="GitHub", token="gh_mixed_token")
    user_credentials_ctx.set((cred1, cred3))
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
        mock_exec.return_value = mock_proc

        await safe_exec("echo hello", allowed_issuers=["github"])

        assert mock_exec.call_count == 1
        _, kwargs = mock_exec.call_args
        passed_env = kwargs.get("env")

        assert passed_env is not None
        assert "GITHUB_TOKEN" in passed_env
        assert passed_env["GITHUB_TOKEN"] == "gh_mixed_token"
        assert "FEISHU_USER_ACCESS_TOKEN" not in passed_env


@pytest.mark.asyncio
async def test_contextvar_thread_propagation() -> None:
    """Verify propagate_user_credentials clones and carries context variables to other threads."""
    cred1 = EphemeralUserCredential(issuer="feishu", token="thread_safe_token")
    user_credentials_ctx.set((cred1,))

    import concurrent.futures

    def thread_worker() -> tuple[EphemeralUserCredential, ...]:
        return user_credentials_ctx.get()

    # Without propagation, thread pool execution should result in LookupError/default value
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(thread_worker)
        results = future.result()
        # ThreadPoolExecutor doesn't copy context, so it gets default ()
        assert len(results) == 0

    # With propagation, context is copied and bound to the executor thread
    propagated_worker = propagate_user_credentials(thread_worker)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(propagated_worker)
        results = future.result()
        assert len(results) == 1
        assert results[0].token == "thread_safe_token"

    # Now, test asynchronous function propagation
    async def async_worker() -> tuple[EphemeralUserCredential, ...]:
        await asyncio.sleep(0.01)
        return user_credentials_ctx.get()

    # Wrap the async worker
    propagated_async_worker = propagate_user_credentials(async_worker)

    # We clear the active context so that we can verify that the wrapper carries the captured context
    token_ctx = user_credentials_ctx.set(())
    try:
        # Since propagated_async_worker carries the captured context, it should still read 'thread_safe_token'
        results = await propagated_async_worker()
        assert len(results) == 1
        assert results[0].token == "thread_safe_token"
    finally:
        user_credentials_ctx.reset(token_ctx)


@pytest.mark.asyncio
async def test_with_user_credentials_context_manager() -> None:
    """Verify with_user_credentials context manager sets and restores credentials correctly."""
    assert len(user_credentials_ctx.get()) == 0

    cred1 = EphemeralUserCredential(issuer="feishu", token="ctx_mgr_token")

    async with with_user_credentials((cred1,)):
        assert user_credentials_ctx.get() == (cred1,)

    assert len(user_credentials_ctx.get()) == 0
