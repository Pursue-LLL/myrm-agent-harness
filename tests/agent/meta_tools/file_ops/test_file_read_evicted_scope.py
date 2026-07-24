"""file_read_tool evicted_uploaded path policy for Fast / search track."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    FileReadInput,
    _assert_evicted_uploaded_read_scope,
    _assert_paths_allowed_for_read,
    _normalize_path_hint,
    _path_hint_allowed_for_evicted_uploaded,
    create_file_read_tool,
)
from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var
from myrm_agent_harness.utils.errors import ToolError

_DUMMY_CONFIG = RunnableConfig()


def test_normalize_path_hint_strips_leading_dot_slash() -> None:
    chat_id = "chat-norm"
    raw = f"./.context/{chat_id}/evicted/web_fetch_ab12cd34.md"
    assert _normalize_path_hint(raw) == f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"
    assert _path_hint_allowed_for_evicted_uploaded(raw, chat_id)


def test_path_hint_allows_evicted_and_uploaded() -> None:
    chat_id = "chat-1"
    assert _path_hint_allowed_for_evicted_uploaded(
        f".context/{chat_id}/evicted/web_fetch_ab12cd34.md", chat_id
    )
    assert _path_hint_allowed_for_evicted_uploaded("_uploaded/report.pdf", chat_id)
    assert _path_hint_allowed_for_evicted_uploaded("_uploaded", chat_id)


def test_path_hint_blocks_workspace_source() -> None:
    assert not _path_hint_allowed_for_evicted_uploaded("src/main.py", "chat-1")
    assert not _path_hint_allowed_for_evicted_uploaded("evil/_uploaded/x.txt", "chat-1")


@pytest.mark.asyncio
async def test_scope_blocks_workspace_file(tmp_path) -> None:
    chat_id = "chat-scope"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    blocked = workspace / "secret.txt"
    blocked.write_text("nope", encoding="utf-8")

    token_ws = workspace_root_var.set(str(workspace))
    token_chat = chat_id_var.set(chat_id)
    try:

        class _Executor:
            async def resolve_path(self, path: str) -> str:
                return str(workspace / path)

        with pytest.raises(ToolError, match="blocked"):
            await _assert_evicted_uploaded_read_scope(
                ["secret.txt"], chat_id=chat_id, executor=_Executor()
            )
    finally:
        workspace_root_var.reset(token_ws)
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_scope_allows_evicted_file(tmp_path) -> None:
    chat_id = "chat-scope-ok"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    spill = evicted_dir / "web_fetch_ab12cd34.md"
    spill.write_text("full page", encoding="utf-8")
    rel = f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"

    token_ws = workspace_root_var.set(str(workspace))
    token_chat = chat_id_var.set(chat_id)
    try:

        class _Executor:
            async def resolve_path(self, path: str) -> str:
                return str(workspace / path)

        await _assert_evicted_uploaded_read_scope(
            [rel], chat_id=chat_id, executor=_Executor()
        )
    finally:
        workspace_root_var.reset(token_ws)
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_scope_missing_chat_id_raises() -> None:
    token_chat = chat_id_var.set("")
    try:
        with pytest.raises(ToolError, match="missing chat_id"):
            await _assert_evicted_uploaded_read_scope(
                [".context/x/evicted/a.md"],
                chat_id="",
                executor=None,
            )
    finally:
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_scope_allows_vault_uri_without_workspace() -> None:
    await _assert_evicted_uploaded_read_scope(
        ["vault://artifact-uuid-1"],
        chat_id="chat-vault",
        executor=None,
    )


@pytest.mark.asyncio
async def test_scope_blocks_when_no_workspace_and_path_not_hint_allowed() -> None:
    with pytest.raises(ToolError, match="blocked"):
        await _assert_evicted_uploaded_read_scope(
            ["reports/summary.md"],
            chat_id="chat-no-ws",
            executor=None,
        )


@pytest.mark.asyncio
async def test_scope_blocks_resolved_path_outside_allowed_roots(tmp_path) -> None:
    chat_id = "chat-outside"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    outside = workspace / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    token_ws = workspace_root_var.set(str(workspace))
    token_chat = chat_id_var.set(chat_id)
    try:

        class _Executor:
            async def resolve_path(self, path: str) -> str:
                return str(outside)

        with pytest.raises(ToolError, match="blocked"):
            await _assert_evicted_uploaded_read_scope(
                ["outside.txt"],
                chat_id=chat_id,
                executor=_Executor(),
            )
    finally:
        workspace_root_var.reset(token_ws)
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_scope_uses_base_when_resolve_path_raises_value_error(tmp_path) -> None:
    chat_id = "chat-value-error"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    spill = evicted_dir / "web_fetch_ab12cd34.md"
    spill.write_text("ok", encoding="utf-8")
    rel = f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"

    token_ws = workspace_root_var.set(str(workspace))
    token_chat = chat_id_var.set(chat_id)
    try:

        class _Executor:
            async def resolve_path(self, path: str) -> str:
                raise ValueError("bad path")

        await _assert_evicted_uploaded_read_scope(
            [rel],
            chat_id=chat_id,
            executor=_Executor(),
        )
    finally:
        workspace_root_var.reset(token_ws)
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_scope_resolve_value_error_falls_back_to_base(tmp_path) -> None:
    chat_id = "chat-resolve-ve"
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)

    token_ws = workspace_root_var.set(str(workspace))
    token_chat = chat_id_var.set(chat_id)
    try:

        class _Executor:
            async def resolve_path(self, path: str) -> str:
                raise ValueError("ambiguous")

        with pytest.raises(ToolError, match="blocked"):
            await _assert_evicted_uploaded_read_scope(
                ["web_fetch_ab12cd34.md"],
                chat_id=chat_id,
                executor=_Executor(),
            )
    finally:
        workspace_root_var.reset(token_ws)
        chat_id_var.reset(token_chat)


@pytest.mark.asyncio
async def test_file_read_tool_evicted_policy_blocks_workspace_path() -> None:
    tool = create_file_read_tool(path_policy="evicted_uploaded")
    chat_id = "chat-tool-block"
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(workspace_path="/tmp"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": chat_id},
    ):
        with pytest.raises(ToolError, match="blocked"):
            await tool.ainvoke({"paths": ["src/main.py"]}, config=_DUMMY_CONFIG)


@pytest.mark.asyncio
async def test_file_read_tool_evicted_policy_allows_spill_path(tmp_path) -> None:
    chat_id = "chat-tool-ok"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    spill = evicted_dir / "web_fetch_ab12cd34.md"
    spill.write_text("spilled body", encoding="utf-8")
    rel = f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(workspace)

    tool = create_file_read_tool(path_policy="evicted_uploaded")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": chat_id},
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        return_value=["spilled body"],
    ):
        result = await tool.ainvoke({"paths": [rel]}, config=_DUMMY_CONFIG)

    assert result == "spilled body"


def test_file_read_input_normalize_paths_from_json_string() -> None:
    parsed = FileReadInput.model_validate({"paths": '["a.md", "b.md"]'})
    assert parsed.paths == ["a.md", "b.md"]


def test_file_read_input_normalize_paths_from_plain_string() -> None:
    parsed = FileReadInput.model_validate({"paths": "single.md"})
    assert parsed.paths == ["single.md"]


@pytest.mark.asyncio
async def test_file_read_tool_url_only_returns_error_message() -> None:
    tool = create_file_read_tool(path_policy="evicted_uploaded")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(workspace_path="/tmp"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": "chat-url"},
    ):
        result = await tool.ainvoke(
            {"paths": ["https://example.com/page"]},
            config=_DUMMY_CONFIG,
        )
    assert isinstance(result, str)
    assert "cannot read URLs" in result


@pytest.mark.asyncio
async def test_assert_paths_allowed_for_read_blocks_disabled_skill() -> None:
    class _Executor:
        async def resolve_path(self, path: str) -> str:
            return f"/disabled-root/{path}"

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_disabled_skill_roots",
        return_value=["/disabled-root"],
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.is_under_disabled_skill_root",
        return_value=True,
    ):
        with pytest.raises(ToolError, match="Path blocked"):
            await _assert_paths_allowed_for_read(
                ["skill/readme.md"],
                _DUMMY_CONFIG,
                _Executor(),
            )


@pytest.mark.asyncio
async def test_file_read_preserve_in_context_wraps_output(tmp_path) -> None:
    chat_id = "chat-preserve"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    spill = evicted_dir / "web_fetch_ab12cd34.md"
    spill.write_text("keep me", encoding="utf-8")
    rel = f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(workspace)
    tool = create_file_read_tool(path_policy="evicted_uploaded")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": chat_id},
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        return_value=["keep me"],
    ):
        result = await tool.ainvoke(
            {"paths": [rel], "preserve_in_context": True},
            config=_DUMMY_CONFIG,
        )

    assert isinstance(result, str)
    assert result.startswith("<preserve_context>")
    assert "keep me" in result


@pytest.mark.asyncio
async def test_assert_paths_allowed_for_read_skips_without_resolve_path() -> None:
    await _assert_paths_allowed_for_read(["file.md"], _DUMMY_CONFIG, object())


@pytest.mark.asyncio
async def test_assert_paths_allowed_for_read_resolve_value_error_continues() -> None:
    class _Executor:
        async def resolve_path(self, path: str) -> str:
            raise ValueError("bad")

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_disabled_skill_roots",
        return_value=["/skills"],
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.is_under_disabled_skill_root",
        return_value=False,
    ):
        await _assert_paths_allowed_for_read(
            ["file.md"],
            _DUMMY_CONFIG,
            _Executor(),
        )


def test_file_read_input_normalize_paths_rejects_non_string_types() -> None:
    assert FileReadInput.normalize_paths(123) is None


@pytest.mark.asyncio
async def test_file_read_permission_error_raises_tool_error(tmp_path) -> None:
    chat_id = "chat-perm"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    rel = f".context/{chat_id}/evicted/web_fetch_ab12cd34.md"

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(workspace)
    tool = create_file_read_tool(path_policy="evicted_uploaded")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": chat_id},
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        side_effect=PermissionError("denied"),
    ):
        with pytest.raises(ToolError, match="denied"):
            await tool.ainvoke({"paths": [rel]}, config=_DUMMY_CONFIG)


@pytest.mark.asyncio
async def test_file_read_not_found_raises_tool_error(tmp_path) -> None:
    chat_id = "chat-missing"
    workspace = tmp_path / "ws"
    evicted_dir = workspace / ".context" / chat_id / "evicted"
    evicted_dir.mkdir(parents=True)
    rel = f".context/{chat_id}/evicted/missing.md"

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(workspace)
    tool = create_file_read_tool(path_policy="evicted_uploaded")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value={"chat_id": chat_id},
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        side_effect=FileNotFoundError("missing.md"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.suggest_similar_paths",
        return_value=[],
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.format_path_not_found_hint",
        return_value="Try another path",
    ):
        with pytest.raises(ToolError, match="missing.md"):
            await tool.ainvoke({"paths": [rel]}, config=_DUMMY_CONFIG)
