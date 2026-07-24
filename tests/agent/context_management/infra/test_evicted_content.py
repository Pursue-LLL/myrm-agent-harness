"""Tests for unified evicted content delivery (UECD)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from myrm_agent_harness.agent.context_management.infra.evicted_content import (
    EVICTED_BASENAME_PATTERN,
    MAX_STORED_CHARS,
    build_delivery_footer,
    build_evicted_basename,
    cap_content_for_storage,
    persist_evicted_content,
)
from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var


def test_cap_content_for_storage_under_limit() -> None:
    text = "hello"
    capped, truncated = cap_content_for_storage(text)
    assert capped == text
    assert truncated is False


def test_cap_content_for_storage_over_limit() -> None:
    body = "x" * (MAX_STORED_CHARS + 100)
    capped, truncated = cap_content_for_storage(body)
    assert truncated is True
    assert len(capped) > MAX_STORED_CHARS
    assert "truncated at" in capped


def test_build_evicted_basename_matches_api_pattern() -> None:
    name = build_evicted_basename("web_fetch", ext="md")
    assert EVICTED_BASENAME_PATTERN.match(name)


def test_build_delivery_footer_includes_offset() -> None:
    footer = build_delivery_footer(
        evicted_basename="web_fetch_abcd1234.md",
        head_text="line1\nline2\nline3",
        rel_path=".context/chat1/evicted/web_fetch_abcd1234.md",
    )
    assert "offset=4" in footer
    assert "file_read_tool" in footer


@pytest.mark.asyncio
async def test_persist_evicted_content_writes_file(tmp_path) -> None:
    workspace = tmp_path
    chat_id = "chat_uecd"
    w_tok = workspace_root_var.set(str(workspace))
    c_tok = chat_id_var.set(chat_id)
    try:
        result = await persist_evicted_content("payload\n" * 100, "web_fetch", ext="md")
        assert result.evicted_ref is not None
        assert result.rel_path is not None
        path = workspace / result.rel_path
        assert path.is_file()
        assert "payload" in path.read_text(encoding="utf-8")
    finally:
        workspace_root_var.reset(w_tok)
        chat_id_var.reset(c_tok)


def test_build_evicted_basename_sanitizes_unknown_source() -> None:
    name = build_evicted_basename("custom_mcp_tool_xyz", ext="md")
    assert name.startswith("tool_")


def test_build_evicted_basename_truncates_long_source() -> None:
    long_source = "web_fetch_" + ("x" * 40)
    name = build_evicted_basename(long_source, ext="txt")
    prefix = name.split("_")[0]
    assert prefix in {"web_fetch", "tool"}
    assert len(name) < 60


@pytest.mark.asyncio
async def test_emit_evicted_ref_dispatches_event() -> None:
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        emit_evicted_ref,
    )

    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        new_callable=AsyncMock,
    ) as dispatch:
        await emit_evicted_ref("web_fetch_abcd1234.md")
        dispatch.assert_awaited_once_with(
            "tool_evicted_ref",
            {"evicted_ref": "web_fetch_abcd1234.md"},
        )


def test_build_evicted_basename_normalizes_invalid_extension() -> None:
    name = build_evicted_basename("web_fetch", ext="exe")
    assert name.endswith(".txt")


def test_write_evicted_content_sync_without_session_context() -> None:
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        write_evicted_content_sync,
    )

    result = write_evicted_content_sync("payload", "output")
    assert result.evicted_ref is None
    assert result.rel_path is None


def test_write_evicted_content_sync_success(tmp_path) -> None:
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        write_evicted_content_sync,
    )

    w_tok = workspace_root_var.set(str(tmp_path))
    c_tok = chat_id_var.set("chat_sync_ok")
    try:
        result = write_evicted_content_sync("sync payload", "output")
        assert result.evicted_ref is not None
        assert result.stored_chars > 0
    finally:
        workspace_root_var.reset(w_tok)
        chat_id_var.reset(c_tok)


def test_write_evicted_content_sync_oserror(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        write_evicted_content_sync,
    )

    w_tok = workspace_root_var.set(str(tmp_path))
    c_tok = chat_id_var.set("chat_oserror")
    try:
        monkeypatch.setattr(
            "myrm_agent_harness.agent.context_management.infra.evicted_content.Path.write_text",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")),
        )
        result = write_evicted_content_sync("payload", "output")
        assert result.evicted_ref is None
    finally:
        workspace_root_var.reset(w_tok)
        chat_id_var.reset(c_tok)


@pytest.mark.asyncio
async def test_persist_evicted_content_without_session_context() -> None:
    result = await persist_evicted_content("payload", "web_fetch")
    assert result.evicted_ref is None


@pytest.mark.asyncio
async def test_persist_evicted_content_oserror(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w_tok = workspace_root_var.set(str(tmp_path))
    c_tok = chat_id_var.set("chat_async_oserror")
    try:
        monkeypatch.setattr(
            "myrm_agent_harness.agent.context_management.infra.evicted_content.async_atomic_write",
            AsyncMock(side_effect=OSError("disk full")),
        )
        result = await persist_evicted_content("payload", "web_fetch")
        assert result.evicted_ref is None
    finally:
        workspace_root_var.reset(w_tok)
        chat_id_var.reset(c_tok)
