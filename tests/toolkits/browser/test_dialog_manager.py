"""Unit tests for DialogManager component.

Tests the four dialog policies: SMART, AUTO_ACCEPT, AUTO_DISMISS, WAIT_FOR_AGENT.
Also tests attach/detach, format_for_snapshot, and respond flows.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.dialog_manager import (
    DialogManager,
    DialogPolicy,
    DialogRecord,
    _PendingDialog,
)


def _make_dialog(dialog_type: str = "alert", message: str = "Test", default_value: str = "") -> MagicMock:
    """Create a mock Dialog object."""
    dialog = MagicMock()
    dialog.type = dialog_type
    dialog.message = message
    dialog.default_value = default_value
    dialog.accept = AsyncMock()
    dialog.dismiss = AsyncMock()
    return dialog


def _make_page() -> MagicMock:
    """Create a mock Page with event listener support."""
    page = MagicMock()
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    return page


# =============================================================================
# Construction
# =============================================================================


def test_default_policy():
    dm = DialogManager()
    assert dm.policy == DialogPolicy.SMART


def test_custom_policy():
    dm = DialogManager(policy=DialogPolicy.AUTO_DISMISS)
    assert dm.policy == DialogPolicy.AUTO_DISMISS


def test_policy_setter():
    dm = DialogManager()
    dm.policy = DialogPolicy.WAIT_FOR_AGENT
    assert dm.policy == DialogPolicy.WAIT_FOR_AGENT


# =============================================================================
# Attach / Detach
# =============================================================================


def test_attach_registers_handler():
    dm = DialogManager()
    page = _make_page()
    dm.attach(page)
    page.on.assert_called_once_with("dialog", dm._handle_dialog)
    assert id(page) in dm._attached_pages


def test_attach_idempotent():
    dm = DialogManager()
    page = _make_page()
    dm.attach(page)
    dm.attach(page)
    assert page.on.call_count == 1


def test_detach_removes_handler():
    dm = DialogManager()
    page = _make_page()
    dm.attach(page)
    dm.detach(page)
    page.remove_listener.assert_called_once_with("dialog", dm._handle_dialog)
    assert id(page) not in dm._attached_pages


def test_detach_unregistered_page():
    dm = DialogManager()
    page = _make_page()
    dm.detach(page)
    page.remove_listener.assert_called_once()


# =============================================================================
# SMART policy
# =============================================================================


@pytest.mark.asyncio
async def test_smart_accepts_alert():
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("alert", "Page loaded")
    await dm._handle_dialog(dialog)
    dialog.accept.assert_awaited_once_with("")
    dialog.dismiss.assert_not_awaited()
    assert len(dm.get_recent()) == 1
    assert dm.get_recent()[0].action_taken == "accepted"


@pytest.mark.asyncio
async def test_smart_accepts_confirm():
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("confirm", "Are you sure?")
    await dm._handle_dialog(dialog)
    dialog.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_smart_accepts_beforeunload():
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("beforeunload", "Leave page?")
    await dm._handle_dialog(dialog)
    dialog.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_smart_dismisses_prompt():
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("prompt", "Enter value")
    await dm._handle_dialog(dialog)
    dialog.dismiss.assert_awaited_once()
    dialog.accept.assert_not_awaited()
    assert dm.get_recent()[0].action_taken == "dismissed"


# =============================================================================
# AUTO_ACCEPT policy
# =============================================================================


@pytest.mark.asyncio
async def test_auto_accept_all_types():
    dm = DialogManager(policy=DialogPolicy.AUTO_ACCEPT)
    for dtype in ("alert", "confirm", "prompt", "beforeunload"):
        dialog = _make_dialog(dtype, f"Test {dtype}", "default_val")
        await dm._handle_dialog(dialog)
        dialog.accept.assert_awaited_once_with("default_val")


# =============================================================================
# AUTO_DISMISS policy
# =============================================================================


@pytest.mark.asyncio
async def test_auto_dismiss_all_types():
    dm = DialogManager(policy=DialogPolicy.AUTO_DISMISS)
    for dtype in ("alert", "confirm", "prompt", "beforeunload"):
        dialog = _make_dialog(dtype, f"Test {dtype}")
        await dm._handle_dialog(dialog)
        dialog.dismiss.assert_awaited_once()


# =============================================================================
# WAIT_FOR_AGENT policy
# =============================================================================


@pytest.mark.asyncio
async def test_wait_for_agent_responds_accept():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=5.0)
    dialog = _make_dialog("confirm", "Delete file?")

    async def _respond_after_delay():
        await asyncio.sleep(0.05)
        await dm.respond(True, "")

    task = asyncio.create_task(_respond_after_delay())
    await dm._handle_dialog(dialog)
    await task

    dialog.accept.assert_awaited_once()
    dialog.dismiss.assert_not_awaited()


@pytest.mark.asyncio
async def test_wait_for_agent_responds_dismiss():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=5.0)
    dialog = _make_dialog("confirm", "Delete file?")

    async def _respond_after_delay():
        await asyncio.sleep(0.05)
        await dm.respond(False, "")

    task = asyncio.create_task(_respond_after_delay())
    await dm._handle_dialog(dialog)
    await task

    dialog.dismiss.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_agent_timeout_fallback():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=0.1)
    dialog = _make_dialog("alert", "Timed out dialog")

    await dm._handle_dialog(dialog)

    dialog.accept.assert_awaited_once()
    records = dm.get_recent()
    assert records[0].handled_by == "timeout"


@pytest.mark.asyncio
async def test_wait_for_agent_timeout_dismisses_prompt():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=0.1)
    dialog = _make_dialog("prompt", "Enter password")

    await dm._handle_dialog(dialog)

    dialog.dismiss.assert_awaited_once()
    records = dm.get_recent()
    assert records[0].handled_by == "timeout"
    assert records[0].action_taken == "dismissed"


# =============================================================================
# respond() method
# =============================================================================


@pytest.mark.asyncio
async def test_respond_no_pending():
    dm = DialogManager(policy=DialogPolicy.SMART)
    result = await dm.respond(True)
    assert "no pending" in result.lower()


# =============================================================================
# get_pending()
# =============================================================================


@pytest.mark.asyncio
async def test_get_pending_shows_waiting_dialogs():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=60.0)
    dialog = _make_dialog("confirm", "Pending?")

    async def _hold_dialog():
        await dm._handle_dialog(dialog)

    task = asyncio.create_task(_hold_dialog())
    await asyncio.sleep(0.05)

    pending = dm.get_pending()
    assert len(pending) == 1
    assert pending[0].dialog_type == "confirm"
    assert pending[0].message == "Pending?"

    await dm.respond(True)
    await task


# =============================================================================
# format_for_snapshot()
# =============================================================================


@pytest.mark.asyncio
async def test_format_for_snapshot_empty():
    dm = DialogManager(policy=DialogPolicy.SMART)
    assert dm.format_for_snapshot() is None


@pytest.mark.asyncio
async def test_format_for_snapshot_with_recent():
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("alert", "Hello World")
    await dm._handle_dialog(dialog)

    output = dm.format_for_snapshot()
    assert output is not None
    assert "Hello World" in output
    assert "auto-accepted" in output

    assert dm.format_for_snapshot() is None


@pytest.mark.asyncio
async def test_format_for_snapshot_with_pending():
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=60.0)
    dialog = _make_dialog("confirm", "Do you want to proceed?")

    async def _hold():
        await dm._handle_dialog(dialog)

    task = asyncio.create_task(_hold())
    await asyncio.sleep(0.05)

    output = dm.format_for_snapshot()
    assert output is not None
    assert "PENDING DIALOG" in output
    assert "Do you want to proceed?" in output

    await dm.respond(True)
    await task


# =============================================================================
# Record history bounded
# =============================================================================


@pytest.mark.asyncio
async def test_recent_bounded():
    dm = DialogManager(policy=DialogPolicy.AUTO_ACCEPT)
    for i in range(20):
        dialog = _make_dialog("alert", f"Dialog {i}")
        await dm._handle_dialog(dialog)

    recent = dm.get_recent()
    assert len(recent) == 10
    assert recent[-1].message == "Dialog 19"


# =============================================================================
# DialogRecord immutability
# =============================================================================


def test_dialog_record_frozen():
    record = DialogRecord(
        dialog_type="alert",
        message="test",
        default_value="",
        timestamp=0.0,
        action_taken="accepted",
        handled_by="smart",
    )
    with pytest.raises(Exception):
        record.message = "modified"


# =============================================================================
# DialogPolicy enum
# =============================================================================


def test_dialog_policy_values():
    assert DialogPolicy.SMART.value == "smart"
    assert DialogPolicy.AUTO_ACCEPT.value == "auto_accept"
    assert DialogPolicy.AUTO_DISMISS.value == "auto_dismiss"
    assert DialogPolicy.WAIT_FOR_AGENT.value == "wait_for_agent"


def test_dialog_policy_from_string():
    assert DialogPolicy("smart") == DialogPolicy.SMART
    assert DialogPolicy("wait_for_agent") == DialogPolicy.WAIT_FOR_AGENT
    with pytest.raises(ValueError):
        DialogPolicy("invalid")


# =============================================================================
# Edge cases: concurrent respond, policy switching, multi-page
# =============================================================================


@pytest.mark.asyncio
async def test_policy_switch_mid_session():
    """Switching policy mid-session applies to next dialog."""
    dm = DialogManager(policy=DialogPolicy.AUTO_ACCEPT)
    dialog1 = _make_dialog("alert", "First")
    await dm._handle_dialog(dialog1)
    dialog1.accept.assert_awaited_once()

    dm.policy = DialogPolicy.AUTO_DISMISS
    dialog2 = _make_dialog("alert", "Second")
    await dm._handle_dialog(dialog2)
    dialog2.dismiss.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_pages_attached():
    """DialogManager can attach to multiple pages."""
    dm = DialogManager()
    page1 = _make_page()
    page2 = _make_page()
    dm.attach(page1)
    dm.attach(page2)
    assert len(dm._attached_pages) == 2
    dm.detach(page1)
    assert len(dm._attached_pages) == 1
    dm.detach(page2)
    assert len(dm._attached_pages) == 0


@pytest.mark.asyncio
async def test_respond_with_prompt_text():
    """WAIT_FOR_AGENT mode passes prompt_text to accept."""
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=5.0)
    dialog = _make_dialog("prompt", "Username?", "default_user")

    async def _respond():
        await asyncio.sleep(0.05)
        await dm.respond(True, "admin")

    task = asyncio.create_task(_respond())
    await dm._handle_dialog(dialog)
    await task

    dialog.accept.assert_awaited_once_with("admin")


@pytest.mark.asyncio
async def test_concurrent_dialogs_wait_for_agent():
    """Multiple dialogs queued in WAIT_FOR_AGENT mode are handled sequentially."""
    dm = DialogManager(policy=DialogPolicy.WAIT_FOR_AGENT, timeout_s=5.0)
    dialog1 = _make_dialog("confirm", "Dialog 1")
    dialog2 = _make_dialog("confirm", "Dialog 2")

    async def _handle_first():
        await dm._handle_dialog(dialog1)

    async def _handle_second():
        await asyncio.sleep(0.02)
        await dm._handle_dialog(dialog2)

    async def _respond_both():
        await asyncio.sleep(0.05)
        result1 = await dm.respond(True)
        assert "accepted" in result1.lower() or "respond" in result1.lower()
        await asyncio.sleep(0.05)
        result2 = await dm.respond(False)
        assert "dismissed" in result2.lower() or "respond" in result2.lower()

    t1 = asyncio.create_task(_handle_first())
    t2 = asyncio.create_task(_handle_second())
    t3 = asyncio.create_task(_respond_both())

    await asyncio.gather(t1, t2, t3)
    dialog1.accept.assert_awaited_once()
    dialog2.dismiss.assert_awaited_once()


@pytest.mark.asyncio
async def test_dialog_exception_doesnt_crash():
    """If dialog.accept() raises, DialogManager handles gracefully."""
    dm = DialogManager(policy=DialogPolicy.AUTO_ACCEPT)
    dialog = _make_dialog("alert", "Error dialog")
    dialog.accept = AsyncMock(side_effect=Exception("Page closed"))

    await dm._handle_dialog(dialog)
    records = dm.get_recent()
    assert len(records) >= 1


@pytest.mark.asyncio
async def test_format_for_snapshot_clears_recent():
    """format_for_snapshot consumes recent records (one-shot reporting)."""
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("alert", "Consumed")
    await dm._handle_dialog(dialog)

    first_call = dm.format_for_snapshot()
    assert first_call is not None
    assert "Consumed" in first_call

    second_call = dm.format_for_snapshot()
    assert second_call is None


@pytest.mark.asyncio
async def test_smart_default_value_on_accept():
    """SMART policy passes default_value to accept (Playwright contract)."""
    dm = DialogManager(policy=DialogPolicy.SMART)
    dialog = _make_dialog("alert", "Hello", "some_default")
    await dm._handle_dialog(dialog)
    dialog.accept.assert_awaited_once_with("some_default")


@pytest.mark.asyncio
async def test_auto_accept_preserves_default_value():
    """AUTO_ACCEPT passes default_value to accept for prompts."""
    dm = DialogManager(policy=DialogPolicy.AUTO_ACCEPT)
    dialog = _make_dialog("prompt", "Enter code", "12345")
    await dm._handle_dialog(dialog)
    dialog.accept.assert_awaited_once_with("12345")


@pytest.mark.asyncio
async def test_policy_setter_validation():
    """Policy setter accepts valid DialogPolicy values."""
    dm = DialogManager()
    dm.policy = DialogPolicy.AUTO_DISMISS
    assert dm.policy == DialogPolicy.AUTO_DISMISS
    dm.policy = DialogPolicy.WAIT_FOR_AGENT
    assert dm.policy == DialogPolicy.WAIT_FOR_AGENT
