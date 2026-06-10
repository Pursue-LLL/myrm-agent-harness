"""Unit tests for ConsentDismisser."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.consent_dismisser import ConsentDismisser


@pytest.fixture
def mock_page() -> MagicMock:
    page = MagicMock()
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def dismisser() -> ConsentDismisser:
    return ConsentDismisser(enabled=True)


@pytest.fixture
def disabled_dismisser() -> ConsentDismisser:
    return ConsentDismisser(enabled=False)


class TestConsentDismisserInit:
    def test_default_enabled(self) -> None:
        d = ConsentDismisser()
        assert d.enabled is True

    def test_explicit_disabled(self) -> None:
        d = ConsentDismisser(enabled=False)
        assert d.enabled is False

    def test_toggle_enabled(self) -> None:
        d = ConsentDismisser(enabled=True)
        d.enabled = False
        assert d.enabled is False


class TestDismissDisabled:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(
        self, disabled_dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        result = await disabled_dismisser.dismiss(mock_page)
        assert result is None
        mock_page.evaluate.assert_not_called()


class TestDismissSuccess:
    @pytest.mark.asyncio
    async def test_returns_message_on_cmp_selector(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": True, "method": "cmp_selector"}
        result = await dismisser.dismiss(mock_page)
        assert result is not None
        assert "cmp_selector" in result
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_message_on_text_match(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": True, "method": "text_match"}
        result = await dismisser.dismiss(mock_page)
        assert result is not None
        assert "text_match" in result

    @pytest.mark.asyncio
    async def test_returns_message_on_shadow_dom(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": True, "method": "shadow_dom"}
        result = await dismisser.dismiss(mock_page)
        assert result is not None
        assert "shadow_dom" in result

    @pytest.mark.asyncio
    async def test_returns_message_on_api_call(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": True, "method": "didomi_api"}
        result = await dismisser.dismiss(mock_page)
        assert result is not None
        assert "didomi_api" in result

    @pytest.mark.asyncio
    async def test_returns_message_on_container_removal(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": True, "method": "container_removal"}
        result = await dismisser.dismiss(mock_page)
        assert result is not None
        assert "container_removal" in result


class TestDismissNoConsent:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_consent_found(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = {"dismissed": False, "method": None}
        result = await dismisser.dismiss(mock_page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_result(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.return_value = None
        result = await dismisser.dismiss(mock_page)
        assert result is None


class TestDismissErrors:
    @pytest.mark.asyncio
    async def test_returns_none_on_js_exception(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.side_effect = Exception("Page closed")
        result = await dismisser.dismiss(mock_page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(
        self, dismisser: ConsentDismisser, mock_page: MagicMock
    ) -> None:
        mock_page.evaluate.side_effect = TimeoutError("Evaluation timed out")
        result = await dismisser.dismiss(mock_page)
        assert result is None
