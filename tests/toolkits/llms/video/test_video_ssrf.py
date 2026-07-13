"""SSRF tests for video media URL resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.llms.video.video_engine import _resolve_image_inputs


@pytest.mark.asyncio
async def test_resolve_image_inputs_blocks_ssrf() -> None:
    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        side_effect=SSRFSecurityError("private IP"),
    ):
        with pytest.raises(ValueError, match="URL blocked by SSRF protection"):
            await _resolve_image_inputs(["http://169.254.169.254/x.png"])


@pytest.mark.asyncio
async def test_resolve_image_inputs_uses_secure_get() -> None:
    mock_resp = MagicMock()
    mock_resp.content = b"png"
    mock_resp.raise_for_status = MagicMock()

    with patch(
        "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ) as mock_secure_get:
        data = await _resolve_image_inputs(["https://example.com/ref.png"])

    mock_secure_get.assert_awaited_once()
    assert data == [b"png"]
