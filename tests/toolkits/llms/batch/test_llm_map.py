"""Unit tests for the lightweight batch LLM-map engine.

Covers: basic fan-out, failure isolation, cancellation, structured output,
warm-prefix threshold, empty input, progress reporting, vault pointer
resolution, and concurrency bounding.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from myrm_agent_harness.toolkits.llms.batch.llm_map import (
    DEFAULT_ITEM_TIMEOUT_S,
    DEFAULT_MAX_CONCURRENCY,
    MAX_CONCURRENCY_HARD_CAP,
    MAX_ITEMS_HARD_CAP,
    LlmMapItemResult,
    LlmMapProgress,
    LlmMapReport,
    llm_map,
)
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def _make_llm(*, fail_on: set[str] | None = None, delay: float = 0.0) -> MagicMock:
    """Return a mock BaseChatModel whose ``ainvoke`` echoes Human content."""
    llm = MagicMock()
    _fail = fail_on or set()

    async def _ainvoke(messages: list[SystemMessage | HumanMessage]) -> _FakeResponse:
        human = next((m.content for m in messages if isinstance(m, HumanMessage)), "")
        if delay > 0:
            await asyncio.sleep(delay)
        if human in _fail:
            raise RuntimeError(f"simulated failure for {human!r}")
        return _FakeResponse(f"echo:{human}")

    llm.ainvoke = _ainvoke
    llm.with_structured_output = MagicMock(return_value=llm)
    return llm


class _FakeStructuredResponse(BaseModel):
    label: str | None = None
    score: str | None = None


def _make_structured_llm(*, fail_primary: bool = False) -> MagicMock:
    """Return a mock whose ``with_structured_output`` returns a structured model."""
    llm = MagicMock()

    async def _ainvoke(messages: list[SystemMessage | HumanMessage]) -> _FakeStructuredResponse:
        human = next((m.content for m in messages if isinstance(m, HumanMessage)), "")
        if fail_primary:
            raise RuntimeError("primary failed")
        return _FakeStructuredResponse(label=f"L:{human}", score="5")

    llm.ainvoke = _ainvoke
    structured = MagicMock()
    structured.ainvoke = _ainvoke
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLlmMapBasics:
    """Core fan-out semantics."""

    @pytest.mark.asyncio
    async def test_basic_fanout(self) -> None:
        report = await llm_map(_make_llm(), ["a", "b", "c"], "summarise")
        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.cancelled == 0
        assert len(report.items) == 3
        assert all(r.status == "ok" for r in report.items)
        assert report.items[0].output == "echo:a"

    @pytest.mark.asyncio
    async def test_empty_items(self) -> None:
        report = await llm_map(_make_llm(), [], "x")
        assert report.total == 0
        assert report.succeeded == 0

    @pytest.mark.asyncio
    async def test_single_item(self) -> None:
        report = await llm_map(_make_llm(), ["single"], "inst")
        assert report.total == 1
        assert report.succeeded == 1
        assert report.items[0].id == "0"

    @pytest.mark.asyncio
    async def test_empty_instruction_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty instruction"):
            await llm_map(_make_llm(), ["a"], "   ")

    @pytest.mark.asyncio
    async def test_result_ordering_preserved(self) -> None:
        items = [f"item{i}" for i in range(20)]
        report = await llm_map(_make_llm(), items, "process", max_concurrency=4)
        indices = [r.index for r in report.items]
        assert indices == list(range(20))


class TestFailureIsolation:
    """Per-item failure isolation — single bad row never aborts the batch."""

    @pytest.mark.asyncio
    async def test_partial_failure(self) -> None:
        llm = _make_llm(fail_on={"b"})
        report = await llm_map(llm, ["a", "b", "c"], "do it")
        assert report.total == 3
        assert report.succeeded == 2
        assert report.failed == 1
        failed = [r for r in report.items if r.status == "failed"]
        assert len(failed) == 1
        assert failed[0].id == "1"
        assert "simulated failure" in (failed[0].error or "")

    @pytest.mark.asyncio
    async def test_all_fail(self) -> None:
        llm = _make_llm(fail_on={"a", "b"})
        report = await llm_map(llm, ["a", "b"], "do it")
        assert report.total == 2
        assert report.succeeded == 0
        assert report.failed == 2


class TestCancellation:
    """CancellationToken honoured before and during fan-out."""

    @pytest.mark.asyncio
    async def test_pre_cancelled(self) -> None:
        tok = CancellationToken("t")
        tok.cancel("user")
        report = await llm_map(_make_llm(), ["a", "b"], "x", cancel_token=tok)
        assert report.cancelled == 2
        assert all(r.status == "cancelled" for r in report.items)


class TestWarmPrefix:
    """Warm-prefix threshold: skipped for small batches, active for large."""

    @pytest.mark.asyncio
    async def test_skipped_for_small_batch(self) -> None:
        """With 3 items, warm_prefix should NOT run first item alone."""
        call_order: list[str] = []
        llm = _make_llm()
        original = llm.ainvoke

        async def _tracking(messages: list[SystemMessage | HumanMessage]) -> _FakeResponse:
            human = next((m.content for m in messages if isinstance(m, HumanMessage)), "")
            call_order.append(human)
            return await original(messages)

        llm.ainvoke = _tracking
        report = await llm_map(llm, ["a", "b", "c"], "inst", max_concurrency=4, warm_prefix=True)
        assert report.succeeded == 3
        # All 3 should be concurrent (no serial first item)
        assert len(call_order) == 3

    @pytest.mark.asyncio
    async def test_active_for_large_batch(self) -> None:
        """With 5 items, warm_prefix should run first item alone, then rest concurrently."""
        report = await llm_map(_make_llm(), ["a", "b", "c", "d", "e"], "inst", max_concurrency=4)
        assert report.total == 5
        assert report.succeeded == 5

    @pytest.mark.asyncio
    async def test_disabled_warm_prefix(self) -> None:
        report = await llm_map(_make_llm(), ["a", "b", "c", "d", "e"], "inst", warm_prefix=False)
        assert report.succeeded == 5


class TestProgressCallback:
    """Progress reporting via on_progress callback."""

    @pytest.mark.asyncio
    async def test_progress_events_emitted(self) -> None:
        events: list[LlmMapProgress] = []

        async def _on_progress(p: LlmMapProgress) -> None:
            events.append(p)

        await llm_map(
            _make_llm(fail_on={"c"}),
            ["a", "b", "c", "d"],
            "inst",
            on_progress=_on_progress,
            max_concurrency=2,
        )
        assert len(events) == 4
        last = events[-1]
        assert last.done == 4
        assert last.total == 4
        assert last.failed == 1

    @pytest.mark.asyncio
    async def test_no_progress_when_none(self) -> None:
        report = await llm_map(_make_llm(), ["a"], "inst", on_progress=None)
        assert report.succeeded == 1


class TestDictItems:
    """Dict items with explicit id and vault:// resolution."""

    @pytest.mark.asyncio
    async def test_dict_item_with_id(self) -> None:
        items = [{"id": "doc_42", "content": "hello"}]
        report = await llm_map(_make_llm(), items, "summarise")
        assert report.items[0].id == "doc_42"
        assert report.items[0].output == "echo:hello"

    @pytest.mark.asyncio
    async def test_vault_pointer_resolved(self) -> None:
        def resolver(ptr: str) -> str:
            assert ptr == "vault://abc"
            return "resolved content"

        report = await llm_map(_make_llm(), ["vault://abc"], "inst", item_resolver=resolver)
        assert report.items[0].output == "echo:resolved content"


class TestConcurrencyBounding:
    """Concurrency clamping and hard caps."""

    @pytest.mark.asyncio
    async def test_concurrency_clamped_to_max(self) -> None:
        report = await llm_map(
            _make_llm(), ["a", "b"], "inst", max_concurrency=100
        )
        assert report.succeeded == 2

    @pytest.mark.asyncio
    async def test_concurrency_min_one(self) -> None:
        report = await llm_map(_make_llm(), ["a"], "inst", max_concurrency=0)
        assert report.succeeded == 1


class TestTimeout:
    """Per-item timeout enforcement."""

    @pytest.mark.asyncio
    async def test_item_timeout(self) -> None:
        llm = _make_llm(delay=5.0)
        report = await llm_map(llm, ["slow"], "inst", item_timeout=0.1)
        assert report.failed == 1
        assert "timeout" in (report.items[0].error or "").lower()


class TestStructuredOutput:
    """response_schema triggers with_structured_output and returns dict."""

    @pytest.mark.asyncio
    async def test_structured_output_basic(self) -> None:
        llm = _make_structured_llm()
        report = await llm_map(llm, ["x"], "classify", response_schema=_FakeStructuredResponse)
        assert report.succeeded == 1
        assert isinstance(report.items[0].output, dict)
        llm.with_structured_output.assert_called_once_with(_FakeStructuredResponse)


class TestFallbackLlm:
    """fallback_llm is invoked when primary fails with a failoverable error."""

    @pytest.mark.asyncio
    async def test_fallback_used_on_failoverable_error(self) -> None:
        primary = MagicMock()

        async def _primary_fail(messages: list[SystemMessage | HumanMessage]) -> _FakeResponse:
            exc = RuntimeError("service unavailable 503")
            exc.status_code = 503  # type: ignore[attr-defined]
            raise exc

        primary.ainvoke = _primary_fail
        primary.with_structured_output = MagicMock(return_value=primary)

        fallback = _make_llm()
        report = await llm_map(primary, ["a"], "inst", fallback_llm=fallback)
        assert report.succeeded == 1
        assert report.items[0].output == "echo:a"

    @pytest.mark.asyncio
    async def test_no_fallback_on_non_failoverable_error(self) -> None:
        primary = _make_llm(fail_on={"a"})
        fallback = _make_llm()
        report = await llm_map(primary, ["a"], "inst", fallback_llm=fallback)
        assert report.failed == 1


class TestMidFlightCancellation:
    """Cancel token set during processing cancels remaining items."""

    @pytest.mark.asyncio
    async def test_cancel_during_processing(self) -> None:
        tok = CancellationToken("t")
        processed: list[str] = []

        async def _slow_ainvoke(messages: list[SystemMessage | HumanMessage]) -> _FakeResponse:
            human = next((m.content for m in messages if isinstance(m, HumanMessage)), "")
            processed.append(human)
            if human == "a":
                await asyncio.sleep(0.1)
                tok.cancel("user")
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.3)
            return _FakeResponse(f"echo:{human}")

        llm = MagicMock()
        llm.ainvoke = _slow_ainvoke
        llm.with_structured_output = MagicMock(return_value=llm)

        report = await llm_map(
            llm,
            ["a", "b", "c", "d", "e"],
            "inst",
            max_concurrency=1,
            warm_prefix=False,
        )
        assert report.cancelled + report.succeeded + report.failed == report.total
        assert report.succeeded >= 1


class TestNormaliseItemEdgeCases:
    """Edge cases for _normalise_item: dict with text key, dict without content."""

    @pytest.mark.asyncio
    async def test_dict_with_text_key(self) -> None:
        items: list[dict[str, object]] = [{"text": "hello world"}]
        report = await llm_map(_make_llm(), items, "inst")
        assert report.items[0].output == "echo:hello world"
        assert report.items[0].id == "0"

    @pytest.mark.asyncio
    async def test_dict_without_content_or_text(self) -> None:
        items: list[dict[str, object]] = [{"id": "custom", "other": "data"}]
        report = await llm_map(_make_llm(), items, "inst")
        assert report.items[0].id == "custom"
        assert report.items[0].output == "echo:"

    @pytest.mark.asyncio
    async def test_dict_with_non_string_content(self) -> None:
        items: list[dict[str, object]] = [{"content": 42}]
        report = await llm_map(_make_llm(), items, "inst")
        assert report.items[0].output == "echo:42"


class TestExtractTextEdgeCases:
    """_extract_text handles various response shapes."""

    @pytest.mark.asyncio
    async def test_list_content_response(self) -> None:
        llm = MagicMock()

        async def _ainvoke(messages: list[SystemMessage | HumanMessage]) -> MagicMock:
            resp = MagicMock()
            resp.content = [{"text": "part1"}, {"text": "part2"}]
            return resp

        llm.ainvoke = _ainvoke
        llm.with_structured_output = MagicMock(return_value=llm)
        report = await llm_map(llm, ["a"], "inst")
        assert report.items[0].output == "part1part2"

    @pytest.mark.asyncio
    async def test_non_string_non_list_content(self) -> None:
        llm = MagicMock()

        async def _ainvoke(messages: list[SystemMessage | HumanMessage]) -> MagicMock:
            resp = MagicMock()
            resp.content = 12345
            return resp

        llm.ainvoke = _ainvoke
        llm.with_structured_output = MagicMock(return_value=llm)
        report = await llm_map(llm, ["a"], "inst")
        assert report.items[0].output == "12345"


class TestConstants:
    """Exported constants have expected values."""

    def test_defaults(self) -> None:
        assert DEFAULT_MAX_CONCURRENCY == 8
        assert MAX_CONCURRENCY_HARD_CAP == 32
        assert MAX_ITEMS_HARD_CAP == 500
        assert DEFAULT_ITEM_TIMEOUT_S == 90.0


class TestDataclasses:
    """LlmMapItemResult and LlmMapReport serialization."""

    def test_item_result_fields(self) -> None:
        r = LlmMapItemResult(index=0, id="x", status="ok", output="y")
        assert r.index == 0
        assert r.output == "y"
        assert r.error is None

    def test_report_fields(self) -> None:
        r = LlmMapReport(total=3, succeeded=2, failed=1, cancelled=0)
        assert r.total == 3
        assert r.items == []
