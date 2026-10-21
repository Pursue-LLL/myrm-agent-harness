"""SSRF tests for image URL downloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.llms.image.generator import _download_reference_images
from myrm_agent_harness.toolkits.llms.image.models import _download_url


@pytest.mark.asyncio
async def test_download_reference_images_blocks_ssrf() -> None:
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        side_effect=SSRFSecurityError("private IP"),
    ):
        result = await _download_reference_images(["http://169.254.169.254/latest/meta-data/"])

    assert result == []


@pytest.mark.asyncio
async def test_download_reference_images_uses_secure_get() -> None:
    mock_resp = MagicMock()
    mock_resp.content = b"png"
    mock_resp.raise_for_status = MagicMock()

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ) as mock_secure_get:
        await _download_reference_images(["https://example.com/ref.png"])

    mock_secure_get.assert_awaited_once()
    assert mock_secure_get.await_args.kwargs["timeout"] == 30.0


@pytest.mark.asyncio
async def test_download_url_blocks_ssrf() -> None:
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        side_effect=SSRFSecurityError("private IP"),
    ):
        result = await _download_url("http://169.254.169.254/")

    assert result is None
