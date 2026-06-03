import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.element_ref.types import ElementRef, SnapshotMeta

@pytest.fixture
def mock_backend():
    return MagicMock()

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.screenshot_delay = 0.0
    return config

@pytest.mark.asyncio
async def test_desktop_interact_revalidation_success(mock_backend, mock_config):
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time() - 6.0  # Force timeout
    session._refs = MagicMock()
    
    mock_meta = SnapshotMeta(ref_count=1, app_name="Test", window_title="Test", scope="foreground", needs_permission=False)
    mock_refs = {"e0": ElementRef(ref_id="e0", role="button", name="Test", bbox=(0,0,10,10), backend_key="key")}
    session._refs.get.return_value = mock_refs["e0"]
    
    with patch("myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot", return_value=(mock_meta, mock_refs)) as mock_capture:
        with patch("myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element") as mock_invoke:
            mock_invoke.return_value.success = True
            session.desktop_snapshot = AsyncMock(return_value="Follow up")
            
            result = await session.desktop_interact(ref="e0", action="click")
            
            mock_capture.assert_called_once_with(mock_backend, "foreground", None)
            session._refs.replace.assert_called_once_with(mock_refs, mock_meta)
            assert "Action 'click' on @e0 succeeded." in result

@pytest.mark.asyncio
async def test_desktop_interact_revalidation_failure_ref_missing(mock_backend, mock_config):
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time() - 6.0  # Force timeout
    session._refs = MagicMock()
    
    mock_meta = SnapshotMeta(ref_count=1, app_name="Test", window_title="Test", scope="foreground", needs_permission=False)
    mock_refs = {"e1": ElementRef(ref_id="e1", role="button", name="Test", bbox=(0,0,10,10), backend_key="key")} # e0 is missing
    
    with patch("myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot", return_value=(mock_meta, mock_refs)):
        result = await session.desktop_interact(ref="e0", action="click")
        
        assert "Safety Re-validation failed" in result
        assert "is no longer found" in result

@pytest.mark.asyncio
async def test_desktop_vision_action_timeout(mock_backend, mock_config):
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time() - 6.0  # Force timeout
    
    result = await session.desktop_vision_action(action="left_click", coordinate=[100, 100])
    
    assert "Safety Re-validation failed" in result
    assert "pixel coordinates are now considered stale and unsafe" in result

@pytest.mark.asyncio
async def test_desktop_vision_action_success(mock_backend, mock_config):
    session = DesktopSession(backend=mock_backend, config=mock_config)
    session._last_snapshot_time = time.time()  # Fresh snapshot
    
    with patch.object(session, "click_at", new_callable=AsyncMock) as mock_click:
        mock_click.return_value.success = True
        mock_click.return_value.screenshot_base64 = ""
        result = await session.desktop_vision_action(action="left_click", coordinate=[100, 100])
        
        assert "completed" in result
        mock_click.assert_called_once()
