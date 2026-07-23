"""Tests for web fetch content spill (head/tail + evicted file)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.infra.evicted_content import (
    build_delivery_footer,
    emit_evicted_ref,
    persist_evicted_content,
)
from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var
from myrm_agent_harness.toolkits.web_fetch.spill import (
    DEFAULT_MODEL_PREVIEW_CHARS,
    emit_web_fetch_evicted_ref,
    maybe_spill_web_fetch_content,
    set_evicted_content_callbacks,
)


@pytest.fixture(autouse=True)
def _inject_evicted_callbacks() -> None:
    """Mirror agent_runtime wiring so spill tests exercise real UECD persist/emit."""
    set_evicted_content_callbacks(
        persist_fn=persist_evicted_content,
        build_footer_fn=build_delivery_footer,
        emit_ref_fn=emit_evicted_ref,
    )


@pytest.mark.asyncio
async def test_spill_skips_small_content() -> None:
    text = "short page"
    result = await maybe_spill_web_fetch_content(text, preview_chars=1000)
    assert result.preview == text
    assert result.evicted_ref is None
    assert result.spilled is False


@pytest.mark.asyncio
async def test_spill_truncates_and_persists_large_content(tmp_path) -> None:
    workspace = tmp_path
    chat_id = "chat_test_1"
    token = workspace_root_var.set(str(workspace))
    chat_token = chat_id_var.set(chat_id)
    try:
        body = "line\n" * 5000
        result = await maybe_spill_web_fetch_content(body, preview_chars=2000)
        assert result.spilled is True
        assert result.evicted_ref is not None
        assert len(result.preview) <= DEFAULT_MODEL_PREVIEW_CHARS + 200
        evicted_path = workspace / ".context" / chat_id / "evicted" / result.evicted_ref
        assert evicted_path.is_file()
        assert evicted_path.read_text(encoding="utf-8") == body
    finally:
        workspace_root_var.reset(token)
        chat_id_var.reset(chat_token)


@pytest.mark.asyncio
async def test_spill_persist_failure_still_returns_preview(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path
    chat_id = "chat_persist_fail"
    token = workspace_root_var.set(str(workspace))
    chat_token = chat_id_var.set(chat_id)

    async def _raise_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "myrm_agent_harness.agent.context_management.infra.evicted_content.async_atomic_write",
        _raise_write,
    )
    try:
        body = "x" * 5000
        result = await maybe_spill_web_fetch_content(body, preview_chars=1000)
        assert result.spilled is True
        assert result.evicted_ref is None
        assert len(result.preview) < len(body)
    finally:
        workspace_root_var.reset(token)
        chat_id_var.reset(chat_token)


@pytest.mark.asyncio
async def test_spill_without_callbacks_truncates_only() -> None:
    from myrm_agent_harness.toolkits.web_fetch import spill as spill_mod

    spill_mod._evicted_callbacks_var.set(None)

    body = "x" * 5000
    result = await maybe_spill_web_fetch_content(body, preview_chars=1000)
    assert result.spilled is True
    assert result.evicted_ref is None
    assert len(result.preview) < len(body)


@pytest.mark.asyncio
async def test_emit_web_fetch_evicted_ref_dispatches_event(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, str]]] = []

    async def _capture(event_type: str, payload: dict[str, str]) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        _capture,
    )
    await emit_web_fetch_evicted_ref("web_fetch_abcd1234.md")
    assert events == [("tool_evicted_ref", {"evicted_ref": "web_fetch_abcd1234.md"})]
