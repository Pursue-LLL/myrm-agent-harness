"""Unit tests for Navigator"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.navigation import Navigator


def _apply_ssrf_guard_stubs(mock_page: MagicMock) -> None:
    """Attach async stubs required by SSRF guard route interception."""
    mock_page.route = AsyncMock()
    mock_page.unroute = AsyncMock()
    mock_page.main_frame = MagicMock()


def create_mock_page(url: str = "http://example.com", status: int = 200, title: str = "Test Page") -> MagicMock:
    """创建完整配置的mock page对象"""
    mock_page = MagicMock()

    mock_request = MagicMock()
    mock_request.url = url
    mock_request.redirected_from = None

    mock_response = MagicMock()
    mock_response.status = status
    mock_response.request = mock_request

    mock_page.goto = AsyncMock(return_value=mock_response)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.title = AsyncMock(return_value=title)
    mock_page.url = url
    mock_page.evaluate = AsyncMock(return_value=None)
    _apply_ssrf_guard_stubs(mock_page)
    return mock_page


class TestNavigator:
    """Navigator 单元测试"""

    @pytest.mark.asyncio
    async def test_goto_http_success(self):
        """测试 http:// URL 允许访问"""
        mock_page = create_mock_page("http://example.com", 200, "Test Page")

        navigator = Navigator(mock_page)
        title, final_url, status = await navigator.goto("http://example.com")

        assert title == "Test Page"
        assert final_url == "http://example.com"
        assert status == 200
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_goto_https_success(self):
        """测试 https:// URL 允许访问"""
        mock_page = create_mock_page("https://example.com", 200, "Secure Page")

        navigator = Navigator(mock_page)
        title, _final_url, status = await navigator.goto("https://example.com")

        assert title == "Secure Page"
        assert status == 200

    @pytest.mark.asyncio
    async def test_goto_about_blank_success(self):
        """测试 about:blank 允许访问"""
        mock_page = create_mock_page("about:blank", 200, "")

        navigator = Navigator(mock_page)
        await navigator.goto("about:blank")

        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_goto_javascript_blocked(self):
        """测试 javascript: URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("javascript:alert(1)")

        assert "Blocked URL scheme: 'javascript' not allowed" in str(exc_info.value)
        assert "javascript/file/data/blob/ftp" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_file_blocked(self):
        """测试 file: URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("file:///etc/passwd")

        assert "Blocked URL scheme: 'file' not allowed" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_data_blocked(self):
        """测试 data: URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("data:text/html,<script>alert(1)</script>")

        assert "Blocked URL scheme: 'data' not allowed" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_blob_blocked(self):
        """测试 blob: URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("blob:https://example.com/uuid")

        assert "Blocked URL scheme: 'blob' not allowed" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_ftp_blocked(self):
        """测试 ftp: URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("ftp://ftp.example.com/file.txt")

        assert "Blocked URL scheme: 'ftp' not allowed" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_missing_scheme(self):
        """测试缺少 scheme 的 URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("example.com")

        assert "Invalid URL: missing scheme" in str(exc_info.value)
        assert "must be http:// or https://" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_case_insensitive(self):
        """测试 scheme 大小写不敏感"""
        mock_page = create_mock_page("HTTP://EXAMPLE.COM", 200, "Test")

        navigator = Navigator(mock_page)
        await navigator.goto("HTTP://EXAMPLE.COM")

        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_goto_relative_url_blocked(self):
        """测试相对 URL 被拦截"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError) as exc_info:
            await navigator.goto("/path/to/page")

        assert "Invalid URL: missing scheme" in str(exc_info.value)
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_goto_stability_wait_integrated(self):
        """测试networkidle等待与导航集成"""
        mock_page = create_mock_page("https://example.com", 200, "Test Page")

        navigator = Navigator(mock_page)
        title, _final_url, status = await navigator.goto("https://example.com")

        assert title == "Test Page"
        assert status == 200
        mock_page.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_goto_response_none(self):
        """测试 response=None 场景（默认 status=200）"""
        mock_page = create_mock_page("http://example.com", 200, "No Response")
        mock_page.goto = AsyncMock(return_value=None)

        navigator = Navigator(mock_page)
        _title, _final_url, status = await navigator.goto("http://example.com")

        assert status == 200

    @pytest.mark.asyncio
    async def test_back(self):
        """测试后退"""
        mock_page = MagicMock()
        mock_page.go_back = AsyncMock()

        navigator = Navigator(mock_page)
        await navigator.back()

        mock_page.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward(self):
        """测试前进"""
        mock_page = MagicMock()
        mock_page.go_forward = AsyncMock()

        navigator = Navigator(mock_page)
        await navigator.forward()

        mock_page.go_forward.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload(self):
        """测试刷新"""
        mock_page = MagicMock()
        mock_page.reload = AsyncMock()

        navigator = Navigator(mock_page)
        await navigator.reload()

        mock_page.reload.assert_called_once()

    def test_get_url(self):
        """测试获取当前 URL"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com/page"

        navigator = Navigator(mock_page)
        url = navigator.get_url()

        assert url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_get_title(self):
        """测试获取页面标题"""
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Page Title")

        navigator = Navigator(mock_page)
        title = await navigator.get_title()

        assert title == "Page Title"

    @pytest.mark.asyncio
    async def test_wait_for_page_ready_success(self):
        """测试networkidle等待成功"""
        mock_page = create_mock_page("https://example.com", 200, "Test Page")

        navigator = Navigator(mock_page)
        title, _final_url, _status = await navigator.goto("https://example.com")

        assert title == "Test Page"
        mock_page.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_wait_for_page_ready_timeout(self):
        """测试networkidle超时仍继续"""
        import asyncio

        mock_page = create_mock_page("https://slow.example.com", 200, "Slow Page")

        async def slow_wait_for_load_state(*args, **kwargs):
            await asyncio.sleep(10)

        mock_page.wait_for_load_state = slow_wait_for_load_state

        navigator = Navigator(mock_page)
        title, _final_url, status = await navigator.goto("https://slow.example.com")

        assert title == "Slow Page"
        assert status == 200

    @pytest.mark.asyncio
    async def test_navigation_wait_config_integration(self):
        """测试NavigationWaitConfig集成"""
        from myrm_agent_harness.toolkits.browser.pool.config import NavigationWaitConfig

        mock_page = create_mock_page()
        wait_config = NavigationWaitConfig(wait_timeout_ms=500)

        navigator = Navigator(mock_page, wait_config=wait_config)
        await navigator.goto("https://example.com")

        assert navigator._wait_config.wait_timeout_ms == 500


class TestNavigatorPrivateNetworks:
    """allow_private_networks 行为测试"""

    @pytest.mark.asyncio
    async def test_private_ip_blocked_by_default(self):
        """默认模式下内网 IP 被 SSRF Guard 阻止"""
        mock_page = create_mock_page("http://192.168.1.1/api", 200, "Private")
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError, match="SSRF"):
            await navigator.goto("http://192.168.1.1/api")

    @pytest.mark.asyncio
    async def test_private_ip_allowed_when_enabled(self):
        """allow_private_networks=True 时内网 IP 允许访问"""
        mock_page = create_mock_page("http://192.168.1.1/api", 200, "Local API")
        navigator = Navigator(mock_page, allow_private_networks=True)

        title, _final_url, status = await navigator.goto("http://192.168.1.1/api")

        assert status == 200
        assert title == "Local API"
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_localhost_blocked_by_default(self):
        """默认模式下 localhost 被 SSRF Guard 阻止"""
        mock_page = create_mock_page("http://127.0.0.1:8080/api", 200, "Local")
        navigator = Navigator(mock_page)

        with pytest.raises(ValueError, match="SSRF"):
            await navigator.goto("http://127.0.0.1:8080/api")

    @pytest.mark.asyncio
    async def test_localhost_allowed_when_enabled(self):
        """allow_private_networks=True 时 localhost 允许访问"""
        mock_page = create_mock_page("http://127.0.0.1:8080/api", 200, "Dev Server")
        navigator = Navigator(mock_page, allow_private_networks=True)

        title, _, status = await navigator.goto("http://127.0.0.1:8080/api")

        assert status == 200
        assert title == "Dev Server"

    @pytest.mark.asyncio
    async def test_scheme_check_preserved_when_private_networks_enabled(self):
        """allow_private_networks=True 时 scheme 检查仍然保留"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page, allow_private_networks=True)

        with pytest.raises(ValueError, match="Blocked URL scheme"):
            await navigator.goto("javascript:alert(1)")

        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_scheme_blocked_when_private_networks_enabled(self):
        """allow_private_networks=True 时 file:// 仍然被阻止"""
        mock_page = MagicMock()
        navigator = Navigator(mock_page, allow_private_networks=True)

        with pytest.raises(ValueError, match="Blocked URL scheme"):
            await navigator.goto("file:///etc/passwd")

        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_ten_network_allowed_when_enabled(self):
        """allow_private_networks=True 时 10.x.x.x 允许访问"""
        mock_page = create_mock_page("http://10.0.0.1/internal", 200, "Internal")
        navigator = Navigator(mock_page, allow_private_networks=True)

        _, _, status = await navigator.goto("http://10.0.0.1/internal")
        assert status == 200

    @pytest.mark.asyncio
    async def test_172_network_allowed_when_enabled(self):
        """allow_private_networks=True 时 172.16.x.x 允许访问"""
        mock_page = create_mock_page("http://172.16.0.1/service", 200, "Service")
        navigator = Navigator(mock_page, allow_private_networks=True)

        _, _, status = await navigator.goto("http://172.16.0.1/service")
        assert status == 200
