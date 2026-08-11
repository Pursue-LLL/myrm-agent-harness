"""Tests for agent-loop MoA advisor fan-out."""

from __future__ import annotations

import asyncio
import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import should_run_fanout
from myrm_agent_harness.toolkits.llms.consensus.advisor_prompts import (
    ADVISOR_SYSTEM,
    build_advisor_injection_block,
)
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import MoAOverlayConfig
from myrm_agent_harness.toolkits.llms.consensus.types import ReferenceResponse


def test_advisor_system_forbids_tool_execution_claims() -> None:
    assert "NOT the acting agent" in ADVISOR_SYSTEM
    assert "NEVER claim you executed" in ADVISOR_SYSTEM


def test_build_advisor_injection_block_formats_refs() -> None:
    refs = [
        ReferenceResponse(model="gpt-a", content="Try approach A", elapsed_seconds=1.0, success=True),
        ReferenceResponse(model="gpt-b", content="Consider B", elapsed_seconds=1.2, success=True),
    ]
    block = build_advisor_injection_block(refs)
    assert "[gpt-a]" in block
    assert "Try approach A" in block
    assert "reference only" in block.lower()


def test_build_advisor_injection_block_empty_and_blank() -> None:
    assert build_advisor_injection_block([]) == ""
    blank = [ReferenceResponse(model="gpt-a", content="  ", elapsed_seconds=1.0, success=True)]
    assert build_advisor_injection_block(blank) == ""


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ([HumanMessage(content="hi")], True),
        ([HumanMessage(content="hi"), AIMessage(content="", tool_calls=[{"id": "1", "name": "t", "args": {}}])], False),
        ([HumanMessage(content="hi"), ToolMessage(content="ok", tool_call_id="1")], False),
    ],
)
def test_should_run_fanout_user_turn(messages: list, expected: bool) -> None:
    assert (
        should_run_fanout(
            messages=messages,
            fanout="user_turn",
            every_n=2,
            iteration=1,
        )
        is expected
    )


def test_should_run_fanout_every_n() -> None:
    msgs = [HumanMessage(content="q")]
    assert should_run_fanout(messages=msgs, fanout="every_n", every_n=3, iteration=3) is True
    assert should_run_fanout(messages=msgs, fanout="every_n", every_n=3, iteration=2) is False


def test_moa_overlay_config_defaults() -> None:
    cfg = MoAOverlayConfig()
    assert cfg.fanout == "user_turn"
    assert cfg.reference_max_tokens == 600
    assert cfg.privacy_filter == "off"


def test_privacy_mode_split() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import (
        inject_privacy_mode,
        sse_privacy_mode,
    )

    assert sse_privacy_mode("display") == "display"
    assert inject_privacy_mode("display") == "off"
    assert inject_privacy_mode("full") == "full"


@pytest.mark.asyncio
async def test_advisor_fanout_cache_hit_replays_on_ref_done() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner([llm], MoAOverlayConfig(fanout="per_iteration"))
    ref = ReferenceResponse(model="ref-a", content="cached", elapsed_seconds=0.1, success=True)
    runner._cache["seed"] = [ref]

    on_ref_done = AsyncMock()
    with patch(
        "myrm_agent_harness.toolkits.llms.consensus.advisor_fanout._state_cache_key",
        return_value="seed",
    ), patch.object(AdvisorFanoutRunner, "_query_references", new_callable=AsyncMock) as query_mock:
        refs = await runner.run([HumanMessage(content="hello")], on_ref_done=on_ref_done)

    assert refs == [ref]
    query_mock.assert_not_called()
    on_ref_done.assert_awaited_once_with(ref)


@pytest.mark.asyncio
async def test_advisor_fanout_calls_on_ref_done_per_completion() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm_a = MagicMock(model_name="ref-a")
    llm_b = MagicMock(model_name="ref-b")
    runner = AdvisorFanoutRunner([llm_a, llm_b], MoAOverlayConfig(fanout="per_iteration"))

    ref_a = ReferenceResponse(model="ref-a", content="A", elapsed_seconds=0.1, success=True)
    ref_b = ReferenceResponse(model="ref-b", content="B", elapsed_seconds=0.2, success=True)
    on_ref_done = AsyncMock()

    async def fake_query_single(_self, llm, _query, _history):
        name = getattr(llm, "model_name", "x")
        return ref_a if name == "ref-a" else ref_b

    with patch.object(AdvisorFanoutRunner, "_query_single", fake_query_single):
        refs = await runner.run(
            [HumanMessage(content="hello")],
            on_ref_done=on_ref_done,
        )

    assert len(refs) == 2
    assert on_ref_done.await_count == 2
    models_seen = {call.args[0].model for call in on_ref_done.await_args_list}
    assert models_seen == {"ref-a", "ref-b"}


def test_apply_privacy_to_ref_uses_injected_redactor() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import apply_privacy_to_ref

    ref = ReferenceResponse(
        model="ref-a",
        content="Contact alice@example.com at 555-0100",
        elapsed_seconds=0.1,
        success=True,
    )
    redacted = apply_privacy_to_ref(ref, "display", redact_fn=lambda text: "REDACTED")
    assert redacted.content == "REDACTED"
    assert redacted.model == ref.model
    assert redacted.success == ref.success


def test_apply_privacy_to_ref_off_passthrough_without_redactor() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import apply_privacy_to_ref

    ref = ReferenceResponse(
        model="ref-a",
        content="raw content",
        elapsed_seconds=0.1,
        success=True,
    )
    assert apply_privacy_to_ref(ref, "off") is ref


def test_apply_privacy_to_ref_missing_redactor_emits_raw_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import apply_privacy_to_ref

    ref = ReferenceResponse(
        model="ref-a",
        content="raw content",
        elapsed_seconds=0.1,
        success=True,
    )
    # fail-open fallback keeps behaviour usable when a caller bypasses the engine guard
    with caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.consensus.advisor_fanout"):
        redacted = apply_privacy_to_ref(ref, "full")
    assert redacted.content == "raw content"
    assert any("no redactor injected" in message for message in caplog.messages)


def test_redact_for_privacy_empty_text_passthrough() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import _redact_for_privacy

    assert _redact_for_privacy("", "full", redact_fn=lambda t: "X") == ""


def test_runner_requires_reference_llms() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    with pytest.raises(ValueError, match="At least one reference LLM"):
        AdvisorFanoutRunner([])


@pytest.mark.asyncio
async def test_runner_iteration_counter() -> None:
    from unittest.mock import MagicMock

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    runner = AdvisorFanoutRunner([MagicMock(model_name="ref-a")])
    assert runner.iteration == 0
    assert runner.next_iteration() == 1
    assert runner.next_iteration() == 2


@pytest.mark.asyncio
async def test_runner_skips_when_fanout_disabled() -> None:
    from unittest.mock import MagicMock

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner([llm], MoAOverlayConfig(fanout="every_n", every_n=3))
    assert await runner.run([HumanMessage(content="q")]) == []


@pytest.mark.asyncio
async def test_runner_skips_without_human_query() -> None:
    from unittest.mock import MagicMock

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner([llm], MoAOverlayConfig(fanout="per_iteration"))
    assert await runner.run([ToolMessage(content="tool done", tool_call_id="1")]) == []


def test_extract_last_human_query_list_content() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import _extract_last_human_query

    msgs = [
        HumanMessage(content="ignored"),
        HumanMessage(content=[{"type": "text", "text": "hello "}, {"type": "image", "image_url": "x"}]),
    ]
    assert _extract_last_human_query(msgs) == "hello"


def test_model_name_fallback_uses_class_name() -> None:
    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    assert AdvisorFanoutRunner._model_name(object()) == "object"


@pytest.mark.asyncio
async def test_query_single_success_and_empty_retry_exhaustion() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner([llm], MoAOverlayConfig(fanout="per_iteration", max_retries_per_model=1))

    with patch(
        "myrm_agent_harness.toolkits.llms.consensus.advisor_fanout.collect_stream",
        new_callable=AsyncMock,
    ) as stream:
        stream.return_value = "   useful answer  "
        ref = await runner._query_single(llm, "q", None)
        assert ref.success and ref.content == "useful answer"

        stream.return_value = "   "
        failed = await runner._query_single(llm, "q", None)
        assert not failed.success and failed.error == "empty response"


@pytest.mark.asyncio
async def test_query_single_timeout_and_exception() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner([llm], MoAOverlayConfig(fanout="per_iteration", max_retries_per_model=1))

    with patch(
        "myrm_agent_harness.toolkits.llms.consensus.advisor_fanout.collect_stream",
        side_effect=TimeoutError,
    ):
        ref = await runner._query_single(llm, "q", None)
        assert not ref.success and "timeout" in ref.error

    with patch(
        "myrm_agent_harness.toolkits.llms.consensus.advisor_fanout.collect_stream",
        side_effect=RuntimeError("boom"),
    ):
        ref = await runner._query_single(llm, "q", None)
        assert not ref.success and ref.error == "boom"


@pytest.mark.asyncio
async def test_query_references_global_timeout() -> None:
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner

    llm = MagicMock(model_name="ref-a")
    runner = AdvisorFanoutRunner(
        [llm],
        MoAOverlayConfig(fanout="per_iteration", timeout_total=0.05),
    )

    async def hanging_query_single(self, _llm, _query, _history) -> ReferenceResponse:
        await asyncio.sleep(10)
        return ReferenceResponse(model="ref-a", content="late", elapsed_seconds=1.0, success=True)

    with patch.object(AdvisorFanoutRunner, "_query_single", hanging_query_single):
        refs = await runner._query_references("q", None)

    assert len(refs) == 1
    assert not refs[0].success and refs[0].error == "global timeout"
