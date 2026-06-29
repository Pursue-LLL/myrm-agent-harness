"""Tests for sensitive application guardrail in safety.py and desktop_session.py.

Covers:
- is_sensitive_app: blocklist matching (financial, communication, password managers)
- Custom blocked/allowed list overrides
- Integration with desktop_snapshot, desktop_interact, desktop_vision_action
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.safety import (
    _SENSITIVE_APPS,
    is_sensitive_app,
)


class TestIsSensitiveApp:
    """is_sensitive_app: detect sensitive foreground applications."""

    def test_empty_app_name_safe(self) -> None:
        assert is_sensitive_app("") is None

    def test_financial_alipay_cn(self) -> None:
        assert is_sensitive_app("支付宝") is not None
        assert "Blocked" in (is_sensitive_app("支付宝") or "")

    def test_financial_alipay_en(self) -> None:
        assert is_sensitive_app("Alipay") is not None

    def test_financial_bank(self) -> None:
        assert is_sensitive_app("招商银行") is not None
        assert is_sensitive_app("工商银行") is not None
        assert is_sensitive_app("Bank of America") is not None
        assert is_sensitive_app("Chase") is not None

    def test_financial_stock(self) -> None:
        assert is_sensitive_app("同花顺") is not None
        assert is_sensitive_app("东方财富") is not None

    def test_communication_wechat(self) -> None:
        assert is_sensitive_app("WeChat") is not None
        assert is_sensitive_app("微信") is not None

    def test_communication_telegram(self) -> None:
        assert is_sensitive_app("Telegram") is not None

    def test_communication_signal(self) -> None:
        assert is_sensitive_app("Signal") is not None

    def test_communication_enterprise(self) -> None:
        assert is_sensitive_app("企业微信") is not None
        assert is_sensitive_app("钉钉") is not None
        assert is_sensitive_app("飞书") is not None

    def test_password_manager_1password(self) -> None:
        assert is_sensitive_app("1Password 7") is not None

    def test_password_manager_bitwarden(self) -> None:
        assert is_sensitive_app("Bitwarden") is not None

    def test_password_manager_keychain(self) -> None:
        assert is_sensitive_app("Keychain Access") is not None
        assert is_sensitive_app("钥匙串访问") is not None

    def test_safe_apps(self) -> None:
        assert is_sensitive_app("Microsoft Excel") is None
        assert is_sensitive_app("Google Chrome") is None
        assert is_sensitive_app("Finder") is None
        assert is_sensitive_app("Terminal") is None
        assert is_sensitive_app("Visual Studio Code") is None
        assert is_sensitive_app("Safari") is None

    def test_case_insensitive(self) -> None:
        assert is_sensitive_app("WECHAT") is not None
        assert is_sensitive_app("telegram") is not None
        assert is_sensitive_app("1PASSWORD") is not None

    def test_substring_match(self) -> None:
        """Sensitive keyword matching works on substrings of app_name."""
        assert is_sensitive_app("com.tencent.xinwei.WeChat") is not None
        assert is_sensitive_app("中国工商银行 Personal") is not None

    def test_custom_blocked(self) -> None:
        assert is_sensitive_app("Slack", custom_blocked=frozenset({"slack"})) is not None
        assert is_sensitive_app("Slack") is None

    def test_custom_allowed_override(self) -> None:
        """Custom allowlist overrides default blocklist."""
        assert is_sensitive_app("WeChat", custom_allowed=frozenset({"wechat"})) is None

    def test_custom_allowed_does_not_affect_others(self) -> None:
        assert is_sensitive_app("支付宝", custom_allowed=frozenset({"wechat"})) is not None

    def test_returns_descriptive_message(self) -> None:
        result = is_sensitive_app("支付宝")
        assert result is not None
        assert "支付宝" in result
        assert "sensitive" in result.lower()

    def test_sensitive_apps_frozenset_non_empty(self) -> None:
        assert len(_SENSITIVE_APPS) > 0
        assert all(isinstance(s, str) for s in _SENSITIVE_APPS)


class TestDesktopSnapshotSensitiveGuard:
    """Integration: desktop_snapshot blocks sensitive apps."""

    @pytest.fixture
    def session(self):
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig

        backend = MagicMock()
        return DesktopSession(backend=backend, config=ComputerUseConfig())

    @pytest.mark.asyncio
    async def test_snapshot_blocked_for_sensitive_app(self, session) -> None:
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        mock_meta = SnapshotMeta(
            ref_count=5, app_name="支付宝", window_title="余额", scope="foreground",
        )
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            return_value=(mock_meta, {}),
        ):
            result = await session.desktop_snapshot()
        assert isinstance(result, str)
        assert "Safety" in result
        assert "Blocked" in result

    @pytest.mark.asyncio
    async def test_snapshot_allowed_for_safe_app(self, session) -> None:
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        mock_meta = SnapshotMeta(
            ref_count=3, app_name="Microsoft Excel", window_title="Sheet1", scope="foreground",
        )
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
                return_value=(mock_meta, {}),
            ),
            patch(
                "myrm_agent_harness.toolkits.computer_use.desktop_session.render_snapshot_tree",
                return_value=("tree text", mock_meta),
            ),
        ):
            result = await session.desktop_snapshot()
        assert isinstance(result, str)
        assert "Safety" not in result


class TestDesktopInteractSensitiveGuard:
    """Integration: desktop_interact blocks on re-validation when sensitive app detected."""

    @pytest.mark.asyncio
    async def test_interact_revalidation_blocks_sensitive_app(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        backend = MagicMock()
        session = DesktopSession(backend=backend, config=ComputerUseConfig())
        session._last_snapshot_time = time.time() - 10.0

        mock_meta = SnapshotMeta(
            ref_count=2, app_name="WeChat", window_title="Chat", scope="foreground",
        )
        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            return_value=(mock_meta, {"btn1": MagicMock()}),
        ):
            result = await session.desktop_interact(ref="btn1", action="click")

        assert isinstance(result, str)
        assert "Safety" in result
        assert "Blocked" in result


class TestDesktopVisionActionSensitiveGuard:
    """Integration: desktop_vision_action blocks when foreground is sensitive."""

    @pytest.mark.asyncio
    async def test_vision_action_blocks_sensitive_app(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        from myrm_agent_harness.toolkits.computer_use.types import ComputerUseConfig

        backend = MagicMock()
        session = DesktopSession(backend=backend, config=ComputerUseConfig())
        session._last_snapshot_time = time.time()

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value={
                "app_name": "1Password 7",
                "window_title": "Vault",
                "interactive_estimate": 10,
                "needs_permission": False,
                "recommendation": "",
            },
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[100, 200],
            )

        assert isinstance(result, str)
        assert "Safety" in result
        assert "Blocked" in result

    @pytest.mark.asyncio
    async def test_vision_action_allows_safe_app(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
        from myrm_agent_harness.toolkits.computer_use.types import (
            ActionResult,
            ComputerUseConfig,
            ScreenContext,
            ScreenInfo,
        )

        backend = MagicMock()
        backend.screen_info.return_value = ScreenInfo(width=1920, height=1080, dpi_scale=1.0)
        backend.screen_context.return_value = ScreenContext(active_window="Chrome", mouse_x=100, mouse_y=200)
        session = DesktopSession(backend=backend, config=ComputerUseConfig())
        session._last_snapshot_time = time.time()
        session.click_at = AsyncMock(
            return_value=ActionResult(success=True, screenshot_base64="img", screenshot_size=(1920, 1080)),
        )

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value={
                "app_name": "Google Chrome",
                "window_title": "Search",
                "interactive_estimate": 50,
                "needs_permission": False,
                "recommendation": "",
            },
        ):
            result = await session.desktop_vision_action(
                action="left_click", coordinate=[100, 200],
            )

        assert not isinstance(result, str) or "Safety" not in result
