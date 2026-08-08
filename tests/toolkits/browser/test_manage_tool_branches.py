"""Tests for uncovered manage.py branches: network, dialog, session, recording, download, site experience."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool


def _make_session() -> MagicMock:
    session = MagicMock()
    session.get_network_detail = AsyncMock(return_value="detail result")
    session.replay_network_request = AsyncMock(return_value="replayed")
    session.set_dialog_response = AsyncMock(return_value="dialog set")
    session.save_session = AsyncMock(return_value="saved")
    session.restore_session = AsyncMock(return_value="restored")
    session.list_sessions = AsyncMock(return_value="sessions list")
    session.delete_session = AsyncMock(return_value="deleted")
    session.start_trace = AsyncMock(return_value="trace started")
    session.stop_trace = AsyncMock(return_value="trace stopped")
    session.start_har = AsyncMock(return_value="har started")
    session.stop_har = AsyncMock(return_value="har stopped")
    session.get_recording_status = MagicMock(return_value="idle")
    session.download_url = AsyncMock()
    session.list_downloads = MagicMock(return_value=[])
    return session


@pytest.fixture
def manage_tool():
    return create_manage_tool(_make_session())


class TestNetworkActions:
    @pytest.mark.asyncio
    async def test_network_detail_success(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_detail", "value": "5"})
        assert "detail result" in result

    @pytest.mark.asyncio
    async def test_network_detail_empty_value(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_detail", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_network_detail_invalid_value(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_detail", "value": "abc"})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_network_replay_success(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_replay", "value": "3"})
        assert "replayed" in result

    @pytest.mark.asyncio
    async def test_network_replay_empty_value(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_replay", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_network_replay_invalid_value(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "network_replay", "value": "xyz"})
        assert "Error" in result


class TestDialogActions:
    @pytest.mark.asyncio
    async def test_dialog_policy_valid(self) -> None:
        session = _make_session()

        session._dialog_manager = MagicMock()
        tool = create_manage_tool(session)
        result = await tool.ainvoke({"action": "dialog_policy", "value": "smart"})
        assert "changed to" in result.lower() or "smart" in result.lower()

    @pytest.mark.asyncio
    async def test_dialog_policy_invalid(self) -> None:
        session = _make_session()
        session._dialog_manager = MagicMock()
        tool = create_manage_tool(session)
        result = await tool.ainvoke({"action": "dialog_policy", "value": "invalid_policy"})
        assert "Invalid" in result or "invalid" in result


class TestSessionVaultActions:
    @pytest.mark.asyncio
    async def test_save_session_success(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "save_session", "value": "github.com"})
        assert "saved" in result

    @pytest.mark.asyncio
    async def test_save_session_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "save_session", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_restore_session_success(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "restore_session", "value": "github.com"})
        assert "restored" in result

    @pytest.mark.asyncio
    async def test_restore_session_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "restore_session", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_sessions(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "list_sessions"})
        assert "sessions list" in result

    @pytest.mark.asyncio
    async def test_delete_session_success(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "delete_session", "value": "github.com"})
        assert "deleted" in result

    @pytest.mark.asyncio
    async def test_delete_session_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "delete_session", "value": ""})
        assert "Error" in result


class TestRecordingActions:
    @pytest.mark.asyncio
    async def test_trace_start(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "trace_start"})
        assert "trace started" in result

    @pytest.mark.asyncio
    async def test_trace_stop(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "trace_stop"})
        assert "trace stopped" in result

    @pytest.mark.asyncio
    async def test_har_start(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "har_start"})
        assert "har started" in result

    @pytest.mark.asyncio
    async def test_har_stop(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "har_stop"})
        assert "har stopped" in result

    @pytest.mark.asyncio
    async def test_recording_status(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "recording_status"})
        assert "idle" in result


class TestDownloadActions:
    @pytest.mark.asyncio
    async def test_download_url_success(self) -> None:
        session = _make_session()
        download_result = MagicMock()
        download_result.file_name = "test.pdf"
        download_result.file_size = 1024
        download_result.path = "/tmp/test.pdf"
        download_result.file_type = "application/pdf"
        session.download_url = AsyncMock(return_value=download_result)
        tool = create_manage_tool(session)
        result = await tool.ainvoke({"action": "download_url", "value": "https://example.com/test.pdf"})
        assert "test.pdf" in result
        assert "1024" in result

    @pytest.mark.asyncio
    async def test_download_url_failure(self) -> None:
        session = _make_session()
        session.download_url = AsyncMock(return_value=None)
        tool = create_manage_tool(session)
        result = await tool.ainvoke({"action": "download_url", "value": "https://example.com/bad"})
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_download_url_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "download_url", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_downloads_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "list_downloads"})
        assert "No files" in result

    @pytest.mark.asyncio
    async def test_list_downloads_with_files(self) -> None:
        session = _make_session()
        dl1 = MagicMock()
        dl1.file_name = "a.pdf"
        dl1.file_size = 512
        dl1.auto_download = False
        dl1.path = "/tmp/a.pdf"
        dl2 = MagicMock()
        dl2.file_name = "b.zip"
        dl2.file_size = 2048
        dl2.auto_download = True
        dl2.path = "/tmp/b.zip"
        session.list_downloads = MagicMock(return_value=[dl1, dl2])
        tool = create_manage_tool(session)
        result = await tool.ainvoke({"action": "list_downloads"})
        assert "a.pdf" in result
        assert "b.zip" in result
        assert "[auto]" in result


_SITE_EXP_STORE = "myrm_agent_harness.toolkits.web_fetch.router.get_global_site_experience_store"
_DOMAIN_METRICS = "myrm_agent_harness.toolkits.web_fetch.router.get_global_domain_metrics_manager"


class TestSiteExperienceActions:
    @pytest.mark.asyncio
    async def test_save_site_experience_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "save_site_experience", "value": ""})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_save_site_experience_invalid_json(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "save_site_experience", "value": "not json"})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_save_site_experience_missing_domain(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "save_site_experience", "value": '{"known_traps":[]}'})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_save_site_experience_success(self, manage_tool) -> None:
        mock_store = MagicMock()
        mock_exp = MagicMock()
        mock_exp.format_full = MagicMock(return_value="saved experience")
        mock_store.save_experience = MagicMock(return_value=mock_exp)

        with patch(_SITE_EXP_STORE, return_value=mock_store):
            result = await manage_tool.ainvoke({
                "action": "save_site_experience",
                "value": '{"domain":"example.com","known_traps":["login wall"]}',
            })
            assert "saved experience" in result

    @pytest.mark.asyncio
    async def test_list_site_experience_empty(self, manage_tool) -> None:
        mock_store = MagicMock()
        mock_store.list_domains = MagicMock(return_value=[])

        with patch(_SITE_EXP_STORE, return_value=mock_store):
            result = await manage_tool.ainvoke({"action": "list_site_experience"})
            assert "No site experience" in result

    @pytest.mark.asyncio
    async def test_list_site_experience_with_domains(self, manage_tool) -> None:
        mock_store = MagicMock()
        mock_store.list_domains = MagicMock(return_value=["example.com"])
        mock_exp = MagicMock()
        mock_store.get = MagicMock(return_value=(mock_exp, False))
        mock_manager = MagicMock()

        with (
            patch(_SITE_EXP_STORE, return_value=mock_store),
            patch(_DOMAIN_METRICS, return_value=mock_manager),
        ):
            result = await manage_tool.ainvoke({"action": "list_site_experience"})
            assert "example.com" in result

    @pytest.mark.asyncio
    async def test_delete_site_experience_success(self, manage_tool) -> None:
        mock_store = MagicMock()
        mock_store.delete = MagicMock(return_value=True)

        with patch(_SITE_EXP_STORE, return_value=mock_store):
            result = await manage_tool.ainvoke({"action": "delete_site_experience", "value": "example.com"})
            assert "Deleted" in result

    @pytest.mark.asyncio
    async def test_delete_site_experience_not_found(self, manage_tool) -> None:
        mock_store = MagicMock()
        mock_store.delete = MagicMock(return_value=False)

        with patch(_SITE_EXP_STORE, return_value=mock_store):
            result = await manage_tool.ainvoke({"action": "delete_site_experience", "value": "nonexist.com"})
            assert "No site experience" in result

    @pytest.mark.asyncio
    async def test_delete_site_experience_empty(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "delete_site_experience", "value": ""})
        assert "Error" in result


class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self, manage_tool) -> None:
        result = await manage_tool.ainvoke({"action": "nonexistent_action"})
        assert "Unknown action" in result
