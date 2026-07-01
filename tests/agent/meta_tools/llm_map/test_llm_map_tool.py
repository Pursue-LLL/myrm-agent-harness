"""Adapter tests for llm_map_tool — guards, vault spill, progress, and preview."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import myrm_agent_harness.agent.meta_tools.llm_map.llm_map_tool as mod
from myrm_agent_harness.agent.meta_tools.llm_map.llm_map_tool import create_llm_map_tool
from myrm_agent_harness.toolkits.llms.batch.llm_map import LlmMapItemResult, LlmMapProgress, LlmMapReport


def _make_llm() -> BaseChatModel:
    llm = MagicMock(spec=BaseChatModel)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    return llm


def _item(index: int, status: str = "ok", output: str = "out", error: str | None = None) -> LlmMapItemResult:
    return LlmMapItemResult(index=index, id=str(index), status=status, output=output, error=error)


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_empty_items() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=5)
    result = await tool.ainvoke({"instruction": "summarise", "items": []})
    assert result["success"] is False
    assert "empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_items_over_cap() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=3)
    result = await tool.ainvoke({"instruction": "classify", "items": ["a", "b", "c", "d"]})
    assert result["success"] is False
    assert result["max_items"] == 3
    assert result["received_items"] == 4
    assert "Split into batches" in result["error"]


@pytest.mark.asyncio
async def test_llm_map_tool_accepts_items_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_report = LlmMapReport(total=2, succeeded=2, failed=0, cancelled=0, items=[])
    mock_llm_map = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(mod, "llm_map", mock_llm_map)

    tool = create_llm_map_tool(_make_llm(), max_items=2)
    result = await tool.ainvoke({"instruction": "tag", "items": ["x", "y"]})
    assert result["success"] is True
    mock_llm_map.assert_awaited_once()
    assert mock_llm_map.await_args.args[1] == ["x", "y"]


@pytest.mark.asyncio
async def test_llm_map_tool_rejects_invalid_output_keys() -> None:
    tool = create_llm_map_tool(_make_llm(), max_items=5)
    result = await tool.ainvoke(
        {"instruction": "classify", "items": ["one"], "output_keys": ["valid-key"]}
    )
    assert result["success"] is False
    assert "identifier" in result["error"].lower()


@pytest.mark.asyncio
async def test_llm_map_tool_accepts_valid_output_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_report = LlmMapReport(total=1, succeeded=1, failed=0, cancelled=0, items=[_item(0)])
    mock_llm_map = AsyncMock(return_value=mock_report)
    monkeypatch.setattr(mod, "llm_map", mock_llm_map)

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke(
        {"instruction": "classify", "items": ["one"], "output_keys": ["label"]}
    )
    assert result["success"] is True
    assert mock_llm_map.await_args.kwargs["response_schema"] is not None


def test_build_schema_valid_identifier() -> None:
    schema = mod._build_schema(["label", "sentiment"])
    model = schema(label="pos", sentiment="happy")
    assert isinstance(model, BaseModel)


def test_resolve_workspace_root_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.code_execution.utils import workspace_path

    monkeypatch.setattr(
        workspace_path.WorkspacePathResolver,
        "resolve_workspace_root",
        MagicMock(side_effect=RuntimeError("no workspace")),
    )
    assert mod._resolve_workspace_root() is None


def test_build_preview_truncates_long_output() -> None:
    long_text = "x" * 500
    report = LlmMapReport(total=1, succeeded=1, failed=0, cancelled=0, items=[_item(0, output=long_text)])
    preview = mod._build_preview(report)
    out = preview[0]["output"]
    assert isinstance(out, str)
    assert out.endswith("…")
    assert len(out) < len(long_text)


def test_spill_results_without_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_resolve_workspace_root", lambda: None)
    assert mod._spill_results([{"index": 0}]) is None


def test_spill_results_success(tmp_path: Path) -> None:
    with patch.object(mod, "_resolve_workspace_root", return_value=str(tmp_path)):
        pointer = mod._spill_results([{"index": 0, "status": "ok"}])
    assert pointer is not None
    assert pointer.startswith("vault://")


def test_spill_results_vault_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_resolve_workspace_root", lambda: "/tmp/ws")
    with patch(
        "myrm_agent_harness.agent.artifacts.vault.ArtifactVault",
        side_effect=RuntimeError("down"),
    ):
        assert mod._spill_results([{"index": 0}]) is None


def test_spill_results_push_inline_artifact_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_resolve_workspace_root", lambda: str(tmp_path))
    with patch(
        "myrm_agent_harness.agent.artifacts.push_inline_artifact",
        side_effect=RuntimeError("ui push failed"),
    ):
        pointer = mod._spill_results([{"index": 0, "status": "ok"}])
    assert pointer is not None


@pytest.mark.asyncio
async def test_llm_map_tool_includes_failures_and_inline_results(monkeypatch: pytest.MonkeyPatch) -> None:
    report = LlmMapReport(
        total=2,
        succeeded=1,
        failed=1,
        cancelled=0,
        items=[_item(0, output="ok"), _item(1, status="failed", output=None, error="boom")],
    )
    monkeypatch.setattr(mod, "llm_map", AsyncMock(return_value=report))

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke({"instruction": "tag", "items": ["a", "b"]})

    assert result["success"] is True
    assert result["failures"] == [{"id": "1", "error": "boom"}]
    assert "results" in result


@pytest.mark.asyncio
async def test_llm_map_tool_spills_oversized_results(monkeypatch: pytest.MonkeyPatch) -> None:
    big_output = "z" * 500
    items = [_item(i, output=big_output) for i in range(20)]
    report = LlmMapReport(total=20, succeeded=20, failed=0, cancelled=0, items=items)
    monkeypatch.setattr(mod, "llm_map", AsyncMock(return_value=report))
    monkeypatch.setattr(mod, "_spill_results", lambda _s: "vault://big")

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke({"instruction": "tag", "items": ["a"] * 20})

    assert result.get("results_vault") == "vault://big"
    assert "note" in result


@pytest.mark.asyncio
async def test_llm_map_tool_spill_fallback_inline_when_vault_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    big_output = "z" * 500
    items = [_item(i, output=big_output) for i in range(20)]
    report = LlmMapReport(total=20, succeeded=20, failed=0, cancelled=0, items=items)
    monkeypatch.setattr(mod, "llm_map", AsyncMock(return_value=report))
    monkeypatch.setattr(mod, "_spill_results", lambda _s: None)

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke({"instruction": "tag", "items": ["a"] * 20})

    assert "results" in result
    assert len(result["results"]) == 20


@pytest.mark.asyncio
async def test_llm_map_tool_emits_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    report = LlmMapReport(total=1, succeeded=1, failed=0, cancelled=0, items=[_item(0)])

    async def _llm_map_with_progress(*_args: object, **kwargs: object) -> LlmMapReport:
        on_progress = kwargs.get("on_progress")
        if on_progress is not None:
            await on_progress(LlmMapProgress(done=1, total=1, failed=0))
        return report

    monkeypatch.setattr(mod, "llm_map", _llm_map_with_progress)

    sink = MagicMock()
    sink.emit = AsyncMock()
    monkeypatch.setattr(
        "myrm_agent_harness.utils.progress_sink.get_tool_progress_sink",
        lambda: sink,
    )

    tool = create_llm_map_tool(_make_llm())
    await tool.ainvoke({"instruction": "tag", "items": ["a"]})

    sink.emit.assert_awaited_once()
    payload = sink.emit.await_args.args[0]
    assert payload["tool"] == mod.TOOL_NAME


@pytest.mark.asyncio
async def test_llm_map_tool_vault_resolver_reads_pointer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

    vault = ArtifactVault(str(tmp_path))
    pointer = vault.put(content=b"resolved-body", filename="item.txt")
    report = LlmMapReport(total=1, succeeded=1, failed=0, cancelled=0, items=[_item(0)])

    async def _llm_map_capture_resolver(*_args: object, **kwargs: object) -> LlmMapReport:
        resolver = kwargs.get("item_resolver")
        assert resolver is not None
        assert resolver(pointer) == "resolved-body"
        return report

    monkeypatch.setattr(mod, "llm_map", _llm_map_capture_resolver)
    monkeypatch.setattr(mod, "_resolve_workspace_root", lambda: str(tmp_path))

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke({"instruction": "tag", "items": [pointer]})
    assert result["success"] is True


@pytest.mark.asyncio
async def test_llm_map_tool_vault_resolver_without_workspace_returns_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    report = LlmMapReport(total=1, succeeded=1, failed=0, cancelled=0, items=[_item(0)])

    async def _llm_map_capture_resolver(*_args: object, **kwargs: object) -> LlmMapReport:
        resolver = kwargs.get("item_resolver")
        assert resolver is not None
        assert resolver("vault://missing") == "vault://missing"
        return report

    monkeypatch.setattr(mod, "llm_map", _llm_map_capture_resolver)
    monkeypatch.setattr(mod, "_resolve_workspace_root", lambda: None)

    tool = create_llm_map_tool(_make_llm())
    result = await tool.ainvoke({"instruction": "tag", "items": ["vault://missing"]})
    assert result["success"] is True
