from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo


class MockLocator:
    def __init__(self, type_attr):
        self.type_attr = type_attr
        self.fill_mock = AsyncMock()
        self.type_mock = AsyncMock()

    async def get_attribute(self, attr, timeout=None):
        if attr == "type":
            return self.type_attr
        return None

    async def fill(self, text, timeout=None):
        await self.fill_mock(text, timeout=timeout)

    async def type(self, text, timeout=None):
        await self.type_mock(text, timeout=timeout)

@pytest.mark.asyncio
async def test_interactor_fill_password_redaction():
    page_mock = MagicMock()
    locator_mock = MockLocator("password")

    get_by_role_mock = MagicMock()
    get_by_role_mock.nth.return_value = locator_mock
    page_mock.get_by_role.return_value = get_by_role_mock

    mock_ref_info = RefInfo(role="textbox", name="password", nth=0)
    interactor = Interactor(page_mock, refs={"e1": mock_ref_info})

    with pytest.MonkeyPatch.context() as m:
        m.setattr("myrm_agent_harness.toolkits.browser.wait_strategies.wait_for_page_ready", AsyncMock())

        with pytest.raises(ValueError, match="strictly forbidden"):
            await interactor.interact(
                action="fill",
                ref="e1",
                text="super_secret_password",
            )

@pytest.mark.asyncio
async def test_interactor_fill_normal_text():
    page_mock = MagicMock()
    locator_mock = MockLocator("text")

    get_by_role_mock = MagicMock()
    get_by_role_mock.nth.return_value = locator_mock
    page_mock.get_by_role.return_value = get_by_role_mock

    mock_ref_info = RefInfo(role="textbox", name="text", nth=0)
    interactor = Interactor(page_mock, refs={"e2": mock_ref_info})

    with pytest.MonkeyPatch.context() as m:
        m.setattr("myrm_agent_harness.toolkits.browser.wait_strategies.wait_for_page_ready", AsyncMock())

        result = await interactor.interact(
            action="fill",
            ref="e2",
            text="hello world"
        )

        assert "hello world" in result
        locator_mock.fill_mock.assert_called_once_with("hello world", timeout=pytest.approx(10000, abs=5000))

@pytest.mark.asyncio
async def test_interactor_type_password_redaction():
    page_mock = MagicMock()
    locator_mock = MockLocator("password")

    get_by_role_mock = MagicMock()
    get_by_role_mock.nth.return_value = locator_mock
    page_mock.get_by_role.return_value = get_by_role_mock

    mock_ref_info = RefInfo(role="textbox", name="password", nth=0)
    interactor = Interactor(page_mock, refs={"e3": mock_ref_info})

    with pytest.MonkeyPatch.context() as m:
        m.setattr("myrm_agent_harness.toolkits.browser.wait_strategies.wait_for_page_ready", AsyncMock())

        with pytest.raises(ValueError, match="strictly forbidden"):
            await interactor.interact(
                action="type",
                ref="e3",
                text="super_secret_password",
            )
