"""Unit tests for SessionPersistence"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.session_persistence import SessionPersistence


@dataclass
class MockSessionEntry:
    """Mock SessionVault Entry"""

    storage_state: dict


class TestSessionPersistence:
    """SessionPersistence 单元测试"""

    @pytest.mark.asyncio
    async def test_save(self):
        """测试保存会话"""
        mock_vault = MagicMock()
        mock_vault.save = AsyncMock()

        mock_context = MagicMock()
        mock_context.storage_state = AsyncMock(
            return_value={
                "cookies": [
                    {"domain": "example.com", "name": "token", "value": "abc"},
                    {"domain": "other.com", "name": "session", "value": "xyz"},
                ],
                "origins": [],
            }
        )

        persistence = SessionPersistence(mock_vault)
        result = await persistence.save(mock_context, "example.com")

        assert "Saved encrypted session" in result
        assert "1 cookies" in result

        mock_vault.save.assert_called_once()
        call_args = mock_vault.save.call_args[1]
        assert call_args["domain"] == "example.com"
        assert len(call_args["storage_state"]["cookies"]) == 1
        assert call_args["storage_state"]["cookies"][0]["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_restore(self):
        """测试恢复会话"""
        mock_vault = MagicMock()
        mock_entry = MockSessionEntry(
            storage_state={
                "cookies": [{"domain": "example.com", "name": "token", "value": "abc"}],
                "origins": [
                    {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "key", "value": "val"}],
                    }
                ],
            }
        )
        mock_vault.load = AsyncMock(return_value=mock_entry)

        mock_context = MagicMock()
        mock_context.add_cookies = AsyncMock()

        mock_temp_page = MagicMock()
        mock_temp_page.route = AsyncMock()
        mock_temp_page.goto = AsyncMock()
        mock_temp_page.evaluate = AsyncMock()
        mock_temp_page.unroute = AsyncMock()
        mock_temp_page.close = AsyncMock()

        mock_context.new_page = AsyncMock(return_value=mock_temp_page)

        mock_page = MagicMock() # no longer directly used for evaluation

        persistence = SessionPersistence(mock_vault)
        result = await persistence.restore(mock_context, mock_page, "example.com")

        assert "Restored encrypted session" in result
        mock_context.add_cookies.assert_called_once()
        mock_context.new_page.assert_called_once()
        mock_temp_page.route.assert_called_once()
        mock_temp_page.goto.assert_called_once()
        mock_temp_page.evaluate.assert_called_once()
        mock_temp_page.unroute.assert_called_once()
        mock_temp_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_not_found(self):
        """测试恢复不存在的会话"""
        mock_vault = MagicMock()
        mock_vault.load = AsyncMock(return_value=None)

        mock_context = MagicMock()
        mock_page = MagicMock()

        persistence = SessionPersistence(mock_vault)
        result = await persistence.restore(mock_context, mock_page, "example.com")

        assert "No saved session found" in result

    @pytest.mark.asyncio
    async def test_list_domains_empty(self):
        """测试列出空会话列表"""
        mock_vault = MagicMock()
        mock_vault.list_domains = AsyncMock(return_value=[])

        persistence = SessionPersistence(mock_vault)
        result = await persistence.list_domains()

        assert result == "No saved sessions"

    @pytest.mark.asyncio
    async def test_list_domains_with_data(self):
        """测试列出会话列表"""
        mock_vault = MagicMock()
        mock_vault.list_domains = AsyncMock(return_value=["github.com", "gitlab.com"])

        persistence = SessionPersistence(mock_vault)
        result = await persistence.list_domains()

        assert "Saved sessions:" in result
        assert "github.com" in result
        assert "gitlab.com" in result

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """测试删除成功"""
        mock_vault = MagicMock()
        mock_vault.delete = AsyncMock(return_value=True)

        persistence = SessionPersistence(mock_vault)
        result = await persistence.delete("example.com")

        assert "Deleted encrypted session" in result

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """测试删除不存在的会话"""
        mock_vault = MagicMock()
        mock_vault.delete = AsyncMock(return_value=False)

        persistence = SessionPersistence(mock_vault)
        result = await persistence.delete("example.com")

        assert "No saved session found" in result

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """测试清理过期会话"""
        mock_vault = MagicMock()
        mock_vault.cleanup_expired = AsyncMock(return_value=3)

        persistence = SessionPersistence(mock_vault)
        removed = await persistence.cleanup_expired()

        assert removed == 3
        mock_vault.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_exception(self):
        """测试清理过期会话异常"""
        mock_vault = MagicMock()
        mock_vault.cleanup_expired = AsyncMock(side_effect=Exception("Cleanup failed"))

        persistence = SessionPersistence(mock_vault)
        removed = await persistence.cleanup_expired()

        assert removed == 0

    @pytest.mark.asyncio
    async def test_compute_hash_success(self):
        """测试 compute_hash 成功"""
        mock_vault = MagicMock()
        mock_entry = MockSessionEntry(
            storage_state={"cookies": [{"name": "a"}]}
        )
        mock_vault.load = AsyncMock(return_value=mock_entry)

        persistence = SessionPersistence(mock_vault)
        hash_val = await persistence.compute_hash("example.com")

        assert hash_val is not None
        assert isinstance(hash_val, str)
        mock_vault.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_compute_hash_not_found(self):
        """测试 compute_hash 未找到会话"""
        mock_vault = MagicMock()
        mock_vault.load = AsyncMock(return_value=None)

        persistence = SessionPersistence(mock_vault)
        hash_val = await persistence.compute_hash("example.com")

        assert hash_val is None

    @pytest.mark.asyncio
    async def test_compute_hash_exception(self):
        """测试 compute_hash 异常"""
        mock_vault = MagicMock()
        mock_vault.load = AsyncMock(side_effect=Exception("Load error"))

        persistence = SessionPersistence(mock_vault)
        hash_val = await persistence.compute_hash("example.com")

        assert hash_val is None

    @pytest.mark.asyncio
    async def test_restore_exception_handling(self):
        """测试 restore 的内部异常处理"""
        mock_vault = MagicMock()
        mock_entry = MockSessionEntry(
            storage_state={
                "cookies": [{"domain": "example.com", "name": "token", "value": "abc"}],
                "origins": [
                    {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "key", "value": "val"}],
                    }
                ],
            }
        )
        mock_vault.load = AsyncMock(return_value=mock_entry)

        mock_context = MagicMock()
        # Trigger an exception during cookie injection
        mock_context.add_cookies = AsyncMock(side_effect=Exception("Cookie error"))
        mock_page = MagicMock()

        persistence = SessionPersistence(mock_vault)
        result = await persistence.restore(mock_context, mock_page, "example.com")

        assert "Error: Failed to inject cookies" in result

        # Test local storage inner exception
        mock_context.add_cookies = AsyncMock() # Reset to succeed
        mock_temp_page = MagicMock()
        mock_temp_page.route = AsyncMock()
        mock_temp_page.goto = AsyncMock(side_effect=Exception("Goto error"))
        mock_temp_page.unroute = AsyncMock()
        mock_temp_page.close = AsyncMock()

        mock_context.new_page = AsyncMock(return_value=mock_temp_page)

        result2 = await persistence.restore(mock_context, mock_page, "example.com")
        assert "Restored encrypted session" in result2
        mock_temp_page.goto.assert_called_once()
        mock_temp_page.evaluate.assert_not_called()

    def test_is_cookie_for_domain_exact_match(self):
        """测试 Cookie 域名精确匹配"""
        assert SessionPersistence._is_cookie_for_domain("example.com", "example.com") is True
        assert SessionPersistence._is_cookie_for_domain("example.com", "sub.example.com") is False

    def test_is_cookie_for_domain_leading_dot(self):
        """测试 Cookie 域名 leading dot 匹配"""
        assert SessionPersistence._is_cookie_for_domain(".example.com", "example.com") is True
        assert SessionPersistence._is_cookie_for_domain(".example.com", "api.example.com") is True
        assert SessionPersistence._is_cookie_for_domain(".example.com", "other.com") is False

    def test_is_cookie_for_domain_case_insensitive(self):
        """测试 Cookie 域名大小写不敏感"""
        assert SessionPersistence._is_cookie_for_domain("Example.COM", "example.com") is True
        assert SessionPersistence._is_cookie_for_domain(".EXAMPLE.COM", "API.example.com") is True
