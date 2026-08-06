"""Live integration tests for SSRF-protected HTTP (no mocks on validation path)."""

from __future__ import annotations

import os

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import secure_get


@pytest.mark.asyncio
async def test_secure_get_blocks_literal_loopback() -> None:
    with pytest.raises(SSRFSecurityError):
        await secure_get("http://127.0.0.1/", timeout=5.0)


@pytest.mark.asyncio
async def test_secure_get_blocks_cloud_metadata_ip() -> None:
    with pytest.raises(SSRFSecurityError):
        await secure_get("http://169.254.169.254/latest/meta-data/", timeout=5.0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_secure_get_lists_opencode_go_models_live() -> None:
    """Real HTTPS DNS-pinned fetch to OpenCode Go models endpoint."""
    api_key = (os.environ.get("BASIC_API_KEY") or "").strip()
    base_url = (os.environ.get("BASIC_BASE_URL") or "https://opencode.ai/zen/go/v1").strip()
    if not api_key or "opencode.ai" not in base_url:
        pytest.skip("OpenCode Go credentials not configured in environment")

    response = await secure_get(
        f"{base_url.rstrip('/')}/models",
        timeout=15.0,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    model_ids = [item["id"] for item in payload.get("data", []) if isinstance(item, dict)]
    assert "deepseek-v4-flash" in model_ids
    assert len(model_ids) >= 20
