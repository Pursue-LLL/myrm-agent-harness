"""Unit tests for Interactor pre-action liveness check and URL change fast-fail."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo


@pytest.fixture
def mock_interactor() -> Interactor:
    page = MagicMock()
    page.url = "https://example.com/checkout"
    page.frames = []

    ref_info = RefInfo(role="button", name="Submit Order", nth=0, bbox=(10, 10, 100, 30))
    refs = {"e1": ref_info}

    interactor = Interactor(
        page=page,
        refs=refs,
        last_snapshot_url="https://example.com/cart",  # Last snapshot was on /cart, but now page navigated to /checkout
    )
    return interactor


@pytest.mark.asyncio
async def test_interactor_fast_fails_when_stale_and_url_navigated(mock_interactor: Interactor) -> None:
    # Mock locator so wait_for attached times out (stale element after navigation)
    mock_locator = MagicMock()
    mock_locator.wait_for = AsyncMock(side_effect=Exception("Timeout 800ms: element detached"))

    with patch(
        "myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator",
        return_value=mock_locator,
    ):
        with pytest.raises(RefNotFoundError) as exc_info:
            await mock_interactor.interact(action="click", ref="e1")

        err_msg = str(exc_info.value)
        assert "Ref not found: e1" in err_msg
        assert "Page has navigated from https://example.com/cart to https://example.com/checkout" in err_msg
