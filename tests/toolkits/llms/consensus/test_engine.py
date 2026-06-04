"""Tests for ConsensusEngine — batch, streaming, cancellation, degradation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.llms.consensus import (
    ConsensusConfig,
    ConsensusEngine,
    ConsensusResult,
    ConsensusStreamEvent,
    ReferenceResponse,
)
from myrm_agent_harness.toolkits.llms.consensus._prompts import AGGREGATOR_SYSTEM
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken


def _make_llm(name: str = "test-model", content: str = "Hello world") -> MagicMock:
    """Create a mock BaseChatModel that streams fixed content.

    Both reference and aggregator calls consume ``astream`` (so the adapter
    records token usage); ``astream_calls`` captures each invocation's messages
    for assertions.
    """
    llm = MagicMock()
    llm.model_name = name
    llm.astream_calls = []

    async def _astream(messages, *args, **kwargs):
        llm.astream_calls.append(messages)
        for word in content.split():
            c = MagicMock()
            c.content = word + " "
            yield c

    llm.astream = _astream
    llm.bind = MagicMock(return_value=llm)
    return llm


def _make_failing_llm(name: str = "fail-model") -> MagicMock:
    """Create a mock BaseChatModel whose stream always raises."""
    llm = MagicMock()
    llm.model_name = name
    llm.astream_calls = []

    async def _astream(messages, *args, **kwargs):
        llm.astream_calls.append(messages)
        raise RuntimeError("model error")
        yield  # unreachable; marks this coroutine as an async generator

    llm.astream = _astream
    llm.bind = MagicMock(return_value=llm)
    return llm


def _make_empty_llm(name: str = "empty-model") -> MagicMock:
    """Create a mock BaseChatModel whose stream yields no content."""
    llm = MagicMock()
    llm.model_name = name
    llm.astream_calls = []

    async def _astream(messages, *args, **kwargs):
        llm.astream_calls.append(messages)
        return
        yield  # unreachable; marks this coroutine as an async generator

    llm.astream = _astream
    llm.bind = MagicMock(return_value=llm)
    return llm


# -----------------------------------------------------------------------
# ConsensusEngine.__init__
# -----------------------------------------------------------------------


class TestEngineInit:
    def test_requires_at_least_one_reference_llm(self):
        with pytest.raises(ValueError, match="At least one reference LLM"):
            ConsensusEngine(reference_llms=[], aggregator_llm=_make_llm())

    def test_default_config(self):
        engine = ConsensusEngine(
            reference_llms=[_make_llm()], aggregator_llm=_make_llm()
        )
        assert engine._cfg.reference_temperature == 0.6
        assert engine._cfg.aggregator_temperature == 0.4

    def test_custom_config(self):
        cfg = ConsensusConfig(min_successful=3, timeout_per_model=60.0)
        engine = ConsensusEngine(
            reference_llms=[_make_llm()],
            aggregator_llm=_make_llm(),
            config=cfg,
        )
        assert engine._cfg.min_successful == 3
        assert engine._cfg.timeout_per_model == 60.0


# -----------------------------------------------------------------------
# ConsensusEngine.run
# -----------------------------------------------------------------------


class TestRun:
    async def test_basic_run(self):
        ref_a = _make_llm("ref-a", "Answer from ref A")
        ref_b = _make_llm("ref-b", "Answer from ref B")
        agg = _make_llm("aggregator", "Final synthesis")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        result = await engine.run("What is 1+1?")

        assert isinstance(result, ConsensusResult)
        assert result.success
        assert result.final_answer == "Final synthesis"
        assert len(result.reference_responses) == 2
        assert all(r.success for r in result.reference_responses)
        assert result.elapsed_seconds > 0

    async def test_multiple_refs(self):
        refs = [_make_llm(f"ref-{i}", f"Answer {i}") for i in range(3)]
        agg = _make_llm("agg", "Combined answer")
        engine = ConsensusEngine(reference_llms=refs, aggregator_llm=agg)

        result = await engine.run("Complex question")

        assert result.success
        assert len(result.reference_responses) == 3
        assert all(r.success for r in result.reference_responses)

    async def test_run_with_system_prompt(self):
        ref = _make_llm("ref", "response")
        agg = _make_llm("agg", "final")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        result = await engine.run("question", system_prompt="Be helpful")
        assert result.success
        assert len(ref.astream_calls) == 1
        assert len(ref.astream_calls[0]) == 2  # SystemMessage + HumanMessage

    async def test_cancel_before_start(self):
        ref = _make_llm("ref")
        agg = _make_llm("agg")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        token = CancellationToken(request_id="test")
        token.cancel()

        result = await engine.run("q", cancel_token=token)

        assert not result.success
        assert result.error == "cancelled"
        assert result.final_answer == ""
        assert ref.astream_calls == []

    async def test_cancel_after_references(self):
        ref = _make_llm("ref", "response")
        agg = _make_llm("agg", "final")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        token = CancellationToken(request_id="test")

        original_query_refs = engine._query_references

        async def _cancel_after_refs(*args, **kwargs):
            result = await original_query_refs(*args, **kwargs)
            token.cancel()
            return result

        engine._query_references = _cancel_after_refs

        result = await engine.run("q", cancel_token=token)
        assert not result.success
        assert result.error == "cancelled"
        assert agg.astream_calls == []

    async def test_insufficient_successful_refs(self):
        fail = _make_failing_llm("fail-1")
        cfg = ConsensusConfig(min_successful=2, max_retries_per_model=1)
        engine = ConsensusEngine(
            reference_llms=[fail],
            aggregator_llm=_make_llm("agg"),
            config=cfg,
        )

        result = await engine.run("q")
        assert not result.success
        assert "0/1" in (result.error or "")


# -----------------------------------------------------------------------
# ConsensusEngine.run_stream
# -----------------------------------------------------------------------


class TestRunStream:
    async def test_stream_basic(self):
        ref_a = _make_llm("ref-a", "Answer from ref A")
        ref_b = _make_llm("ref-b", "Answer from ref B")
        agg = _make_llm("agg", "Aggregated answer")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("question"):
            events.append(event)

        ref_done_events = [e for e in events if e.kind == "ref_done"]
        agg_chunk_events = [e for e in events if e.kind == "agg_chunk"]
        done_events = [e for e in events if e.kind == "done"]

        assert len(ref_done_events) == 2
        assert all(e.ref is not None and e.ref.success for e in ref_done_events)
        assert len(agg_chunk_events) >= 1
        assert len(done_events) == 1
        assert done_events[0].result is not None
        assert done_events[0].result.success

    async def test_stream_cancel_before_start(self):
        ref = _make_llm("ref")
        agg = _make_llm("agg")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        token = CancellationToken(request_id="test")
        token.cancel()

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q", cancel_token=token):
            events.append(event)

        assert len(events) == 1
        assert events[0].kind == "done"
        assert not events[0].result.success
        assert events[0].result.error == "cancelled"

    async def test_stream_cancel_during_aggregation(self):
        ref_a = _make_llm("ref-a", "response a")
        ref_b = _make_llm("ref-b", "response b")
        agg = _make_llm("agg", "long aggregated response here")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        token = CancellationToken(request_id="test")

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q", cancel_token=token):
            events.append(event)
            if event.kind == "agg_chunk":
                token.cancel()

        assert any(e.kind == "ref_done" for e in events)
        done = [e for e in events if e.kind == "done"]
        assert len(done) == 1

    async def test_stream_insufficient_refs(self):
        fail = _make_failing_llm("fail")
        cfg = ConsensusConfig(min_successful=2, max_retries_per_model=1)
        engine = ConsensusEngine(
            reference_llms=[fail], aggregator_llm=_make_llm("agg"), config=cfg
        )

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q"):
            events.append(event)

        done = [e for e in events if e.kind == "done"]
        assert len(done) == 1
        assert not done[0].result.success

    async def test_stream_multiple_refs(self):
        refs = [_make_llm(f"ref-{i}", f"Answer {i}") for i in range(3)]
        agg = _make_llm("agg", "Combined")
        engine = ConsensusEngine(reference_llms=refs, aggregator_llm=agg)

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q"):
            events.append(event)

        ref_dones = [e for e in events if e.kind == "ref_done"]
        assert len(ref_dones) == 3


# -----------------------------------------------------------------------
# Degradation & edge cases
# -----------------------------------------------------------------------


class TestDegradation:
    async def test_aggregator_failure_falls_back_to_best_ref(self):
        ref_short = _make_llm("ref-short", "Short")
        ref_long = _make_llm("ref-long", "This is a much longer response from the model")
        agg = _make_llm("agg")

        async def _failing_stream(messages, *args, **kwargs):
            raise RuntimeError("aggregator down")
            yield  # unreachable; marks this coroutine as an async generator

        agg.astream = _failing_stream

        engine = ConsensusEngine(
            reference_llms=[ref_short, ref_long], aggregator_llm=agg
        )
        result = await engine.run("q")

        assert result.success
        assert result.final_answer == "This is a much longer response from the model"

    async def test_partial_ref_failure_still_succeeds(self):
        good = _make_llm("good", "Good answer")
        bad = _make_failing_llm("bad")
        agg = _make_llm("agg", "Synthesis")
        cfg = ConsensusConfig(min_successful=1, max_retries_per_model=1)

        engine = ConsensusEngine(
            reference_llms=[good, bad], aggregator_llm=agg, config=cfg
        )
        result = await engine.run("q")

        assert result.success
        assert len(result.reference_responses) == 2
        assert sum(1 for r in result.reference_responses if r.success) == 1

    async def test_empty_ref_response_retries(self):
        empty = _make_empty_llm("empty")
        agg = _make_llm("agg", "Final")
        cfg = ConsensusConfig(min_successful=1, max_retries_per_model=2)

        engine = ConsensusEngine(
            reference_llms=[empty], aggregator_llm=agg, config=cfg
        )
        result = await engine.run("q")

        assert not result.reference_responses[0].success
        assert len(empty.astream_calls) == 2

    async def test_stream_aggregator_failure_falls_back(self):
        ref_short = _make_llm("ref-short", "Short ref")
        ref_long = _make_llm("ref-long", "A good reference response with details")
        agg = MagicMock()
        agg.model_name = "agg"

        async def _fail_astream(*args, **kwargs):
            raise RuntimeError("stream failed")
            yield

        agg.astream = _fail_astream
        agg.bind = MagicMock(return_value=agg)

        engine = ConsensusEngine(
            reference_llms=[ref_short, ref_long], aggregator_llm=agg
        )

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q"):
            events.append(event)

        agg_text = "".join(e.chunk for e in events if e.kind == "agg_chunk")
        assert agg_text == "A good reference response with details"
        done = [e for e in events if e.kind == "done"]
        assert done[0].result.success


# -----------------------------------------------------------------------
# _model_name extraction
# -----------------------------------------------------------------------


class TestModelName:
    def test_model_name_attr(self):
        llm = MagicMock()
        llm.model_name = "anthropic/claude-sonnet-4"
        assert ConsensusEngine._model_name(llm) == "anthropic/claude-sonnet-4"

    def test_model_attr_fallback(self):
        llm = MagicMock(spec=[])
        llm.model = "openai/gpt-4.1"
        assert ConsensusEngine._model_name(llm) == "openai/gpt-4.1"

    def test_class_name_fallback(self):
        llm = MagicMock(spec=[])
        del llm.model_name
        del llm.model
        del llm.name
        assert "Mock" in ConsensusEngine._model_name(llm)


# -----------------------------------------------------------------------
# ConsensusStreamEvent typing
# -----------------------------------------------------------------------


class TestTimeouts:
    async def test_global_timeout_returns_failure(self):
        import asyncio

        async def _slow_astream(messages, *args, **kwargs):
            await asyncio.sleep(10)
            yield MagicMock(content="slow")

        slow = MagicMock()
        slow.model_name = "slow-model"
        slow.astream = _slow_astream
        slow.bind = MagicMock(return_value=slow)

        cfg = ConsensusConfig(timeout_total=0.1, max_retries_per_model=1)
        engine = ConsensusEngine(
            reference_llms=[slow], aggregator_llm=_make_llm("agg"), config=cfg
        )
        result = await engine.run("q")

        assert not result.reference_responses[0].success
        assert result.reference_responses[0].error == "global timeout"

    async def test_per_model_timeout(self):
        import asyncio

        async def _slow_astream(messages, *args, **kwargs):
            await asyncio.sleep(10)
            yield MagicMock(content="slow")

        slow = MagicMock()
        slow.model_name = "slow-model"
        slow.astream = _slow_astream
        slow.bind = MagicMock(return_value=slow)

        cfg = ConsensusConfig(
            timeout_per_model=0.1,
            timeout_total=30.0,
            max_retries_per_model=1,
            min_successful=1,
        )
        engine = ConsensusEngine(
            reference_llms=[slow], aggregator_llm=_make_llm("agg"), config=cfg
        )
        result = await engine.run("q")

        assert not result.reference_responses[0].success
        assert "timeout" in (result.reference_responses[0].error or "")

    async def test_stream_cancel_after_references(self):
        ref = _make_llm("ref", "response")
        agg = _make_llm("agg", "aggregated output")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        token = CancellationToken(request_id="test")

        original_query_refs = engine._query_references

        async def _cancel_after_refs(*args, **kwargs):
            result = await original_query_refs(*args, **kwargs)
            token.cancel()
            return result

        engine._query_references = _cancel_after_refs

        events: list[ConsensusStreamEvent] = []
        async for event in engine.run_stream("q", cancel_token=token):
            events.append(event)

        done_events = [e for e in events if e.kind == "done"]
        assert len(done_events) == 1
        assert not done_events[0].result.success
        assert done_events[0].result.error == "cancelled"

    async def test_aggregator_empty_retries_once(self):
        ref_a = _make_llm("ref-a", "reference answer a")
        ref_b = _make_llm("ref-b", "reference answer b")

        call_count = 0

        async def _empty_then_ok(messages, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            content = "" if call_count == 1 else "Final answer"
            for word in content.split():
                c = MagicMock()
                c.content = word + " "
                yield c

        agg = MagicMock()
        agg.model_name = "agg"
        agg.astream = _empty_then_ok
        agg.bind = MagicMock(return_value=agg)

        engine = ConsensusEngine(
            reference_llms=[ref_a, ref_b], aggregator_llm=agg
        )
        result = await engine.run("q")

        assert result.success
        assert result.final_answer == "Final answer"
        assert call_count == 2


class TestStreamEventTypes:
    def test_kind_is_literal(self):
        from typing import Literal, get_type_hints

        hints = get_type_hints(ConsensusStreamEvent, localns={"Literal": Literal})
        kind_type = str(hints["kind"])
        assert "Literal" in kind_type

    def test_ref_done_event(self):
        ref = ReferenceResponse(model="m", content="c", elapsed_seconds=1.0, success=True)
        event = ConsensusStreamEvent(kind="ref_done", ref=ref)
        assert event.kind == "ref_done"
        assert event.ref is ref
        assert event.chunk is None
        assert event.result is None

    def test_agg_chunk_event(self):
        event = ConsensusStreamEvent(kind="agg_chunk", chunk="hello ")
        assert event.kind == "agg_chunk"
        assert event.chunk == "hello "

    def test_done_event(self):
        result = ConsensusResult(final_answer="answer")
        event = ConsensusStreamEvent(kind="done", result=result)
        assert event.kind == "done"
        assert event.result is result


# -----------------------------------------------------------------------
# Cost attribution — tracker propagation through parallel references
# -----------------------------------------------------------------------


def _make_recording_llm(name: str, content: str, tokens: int) -> MagicMock:
    """Mock LLM whose stream records token usage, mirroring the real adapter."""
    from myrm_agent_harness.utils.token_economics.tracker import record_token_usage

    llm = MagicMock()
    llm.model_name = name

    async def _astream(messages, *args, **kwargs):
        record_token_usage(
            {
                "prompt_tokens": tokens,
                "completion_tokens": tokens,
                "total_tokens": tokens * 2,
            },
            model_name=name,
        )
        for word in content.split():
            chunk = MagicMock()
            chunk.content = word + " "
            yield chunk

    llm.astream = _astream
    llm.bind = MagicMock(return_value=llm)
    return llm


class TestCostAttribution:
    async def test_all_calls_recorded_to_request_tracker(self):
        """Parallel references (via ``asyncio.gather``) and the streaming
        aggregator must all record into the single request-scoped tracker.

        Proves the ContextVar set before the run propagates into the copied
        contexts of gathered reference tasks and the inline aggregator stream.
        """
        from myrm_agent_harness.utils.token_economics.tracker import (
            get_token_tracker,
            init_token_tracker,
            reset_token_tracker,
        )

        ref_a = _make_recording_llm("ref-a", "answer a", 10)
        ref_b = _make_recording_llm("ref-b", "answer b", 20)
        agg = _make_recording_llm("agg", "final answer", 30)
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        init_token_tracker()
        try:
            async for _ in engine.run_stream("q"):
                pass

            tracker = get_token_tracker()
            assert tracker is not None
            assert tracker.call_count == 3  # 2 refs + 1 aggregator
            assert tracker.usage.prompt_tokens == 10 + 20 + 30
            assert tracker.usage.total_tokens == (10 + 20 + 30) * 2
            assert set(tracker.model_usage) == {"ref-a", "ref-b", "agg"}
        finally:
            reset_token_tracker()


# -----------------------------------------------------------------------
# Temperature separation — the MoA diversity lever
# -----------------------------------------------------------------------


class TestTemperatureSeparation:
    """Each role's configured sampling temperature must reach the model call.

    References sample hotter (diverse perspectives), the aggregator colder
    (focused synthesis). The engine binds temperature per call rather than
    mutating the shared, cached model instance.
    """

    async def test_batch_run_binds_per_role_temperature(self):
        ref_a = _make_llm("ref-a", "reference answer a")
        ref_b = _make_llm("ref-b", "reference answer b")
        agg = _make_llm("agg", "synthesis")
        cfg = ConsensusConfig(reference_temperature=0.9, aggregator_temperature=0.1)

        engine = ConsensusEngine(
            reference_llms=[ref_a, ref_b], aggregator_llm=agg, config=cfg
        )
        result = await engine.run("q")

        assert result.success
        ref_a.bind.assert_called_with(temperature=0.9)
        ref_b.bind.assert_called_with(temperature=0.9)
        agg.bind.assert_called_with(temperature=0.1)

    async def test_stream_run_binds_per_role_temperature(self):
        ref_a = _make_llm("ref-a", "reference answer a")
        ref_b = _make_llm("ref-b", "reference answer b")
        agg = _make_llm("agg", "synthesis")
        cfg = ConsensusConfig(reference_temperature=0.8, aggregator_temperature=0.2)

        engine = ConsensusEngine(
            reference_llms=[ref_a, ref_b], aggregator_llm=agg, config=cfg
        )
        async for _ in engine.run_stream("q"):
            pass

        ref_a.bind.assert_called_with(temperature=0.8)
        agg.bind.assert_called_with(temperature=0.2)


# -----------------------------------------------------------------------
# Reasoning-content fallback — robustness for reasoning models
# -----------------------------------------------------------------------


class TestReasoningFallback:
    """Reasoning models (DeepSeek-R1, GLM) may stream the answer in
    ``reasoning_content`` with empty ``content``; the engine must use it
    rather than discarding the response as empty.
    """

    async def test_reasoning_content_used_when_content_empty(self):
        def _reasoning_ref(name: str, reasoning: str) -> MagicMock:
            llm = MagicMock()
            llm.model_name = name

            async def _astream(messages, *args, **kwargs):
                for word in reasoning.split():
                    chunk = MagicMock()
                    chunk.content = ""
                    chunk.additional_kwargs = {"reasoning_content": word + " "}
                    yield chunk

            llm.astream = _astream
            llm.bind = MagicMock(return_value=llm)
            return llm

        ref = _reasoning_ref("r1", "the reasoned answer")
        agg = _make_llm("agg", "synthesis")
        cfg = ConsensusConfig(max_retries_per_model=1)

        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg, config=cfg)
        result = await engine.run("q")

        assert result.success
        assert result.reference_responses[0].success
        assert result.reference_responses[0].content == "the reasoned answer"

    async def test_content_preferred_over_reasoning(self):
        def _mixed_ref(name: str) -> MagicMock:
            llm = MagicMock()
            llm.model_name = name

            async def _astream(messages, *args, **kwargs):
                think = MagicMock()
                think.content = ""
                think.additional_kwargs = {"reasoning_content": "thinking "}
                yield think
                answer = MagicMock()
                answer.content = "real answer"
                answer.additional_kwargs = {}
                yield answer

            llm.astream = _astream
            llm.bind = MagicMock(return_value=llm)
            return llm

        ref = _mixed_ref("r1")
        agg = _make_llm("agg", "synthesis")

        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)
        result = await engine.run("q")

        assert result.reference_responses[0].content == "real answer"

    async def test_streaming_aggregator_reasoning_flushed(self):
        """A reasoning-only streaming aggregator must flush its synthesis.

        Without the fallback the aggregator yields no ``content`` chunks, so
        ``run_stream`` would silently degrade to the longest raw reference
        answer and lose the synthesis entirely.
        """

        def _reasoning_agg(name: str, reasoning: str) -> MagicMock:
            llm = MagicMock()
            llm.model_name = name

            async def _astream(messages, *args, **kwargs):
                for word in reasoning.split():
                    chunk = MagicMock()
                    chunk.content = ""
                    chunk.additional_kwargs = {"reasoning_content": f"{word} "}
                    yield chunk

            llm.astream = _astream
            llm.bind = MagicMock(return_value=llm)
            return llm

        ref_a = _make_llm("ref-a", "a solid reference answer")
        ref_b = _make_llm("ref-b", "another solid reference answer")
        agg = _reasoning_agg("agg-r1", "synthesised final answer")

        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        events = [event async for event in engine.run_stream("q")]

        agg_chunks = [e.chunk for e in events if e.kind == "agg_chunk"]
        assert agg_chunks, "reasoning synthesis must be flushed as agg_chunk(s)"
        assert "".join(agg_chunks).strip() == "synthesised final answer"

        done = [e for e in events if e.kind == "done"]
        assert done[0].result.success
        assert done[0].result.final_answer.strip() == "synthesised final answer"


# -----------------------------------------------------------------------
# Single-reference skip — bypass the aggregator for a lone successful ref
# -----------------------------------------------------------------------


class TestSingleReferenceSkip:
    """One successful reference is returned verbatim: the aggregator is skipped
    to save a model call and to avoid its "do not simply repeat" instruction
    degrading a lone, already-correct answer.
    """

    async def test_batch_skips_aggregator(self):
        ref = _make_llm("ref", "The one true answer")
        agg = _make_llm("agg", "should not run")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        result = await engine.run("q")

        assert result.success
        assert result.final_answer == "The one true answer"
        assert agg.astream_calls == []
        agg.bind.assert_not_called()

    async def test_stream_skips_aggregator(self):
        ref = _make_llm("ref", "The one true answer")
        agg = _make_llm("agg", "should not run")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        events = [e async for e in engine.run_stream("q")]

        agg_text = "".join(e.chunk for e in events if e.kind == "agg_chunk")
        assert agg_text == "The one true answer"
        done = [e for e in events if e.kind == "done"]
        assert done[0].result.success
        assert done[0].result.final_answer == "The one true answer"
        assert agg.astream_calls == []

    async def test_lone_survivor_after_partial_failure_skips_aggregator(self):
        good = _make_llm("good", "Solo survivor answer")
        bad = _make_failing_llm("bad")
        agg = _make_llm("agg", "should not run")
        cfg = ConsensusConfig(min_successful=1, max_retries_per_model=1)
        engine = ConsensusEngine(
            reference_llms=[good, bad], aggregator_llm=agg, config=cfg
        )

        result = await engine.run("q")

        assert result.success
        assert result.final_answer == "Solo survivor answer"
        assert agg.astream_calls == []


# -----------------------------------------------------------------------
# Mid-stream aggregator failure — keep partial synthesis, never garble
# -----------------------------------------------------------------------


class TestMidStreamFailure:
    async def test_partial_synthesis_kept_no_best_ref_splice(self):
        """When the aggregator fails after emitting partial synthesis, the
        partial text is preserved as-is. Splicing a full raw reference onto a
        half-written synthesis would corrupt the answer, so the best-ref
        fallback fires only when nothing has streamed yet.
        """
        ref_a = _make_llm("ref-a", "ALPHA reference content")
        ref_b = _make_llm(
            "ref-b", "BRAVO a much longer reference that would win best-ref"
        )

        agg = MagicMock()
        agg.model_name = "agg"

        async def _astream(messages, *args, **kwargs):
            for word in ["partial", "synthesis"]:
                chunk = MagicMock()
                chunk.content = word + " "
                yield chunk
            raise RuntimeError("mid-stream boom")

        agg.astream = _astream
        agg.bind = MagicMock(return_value=agg)

        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        events = [e async for e in engine.run_stream("q")]

        agg_text = "".join(e.chunk for e in events if e.kind == "agg_chunk")
        assert agg_text == "partial synthesis "
        assert "ALPHA" not in agg_text
        assert "BRAVO" not in agg_text
        done = [e for e in events if e.kind == "done"]
        assert done[0].result.success
        assert done[0].result.final_answer == "partial synthesis "


# -----------------------------------------------------------------------
# Persona threading — the aggregator must honour the agent system prompt
# -----------------------------------------------------------------------


class TestAggregatorPersona:
    """The aggregator synthesis is streamed straight to the user as the final
    reply, so it must inherit the agent persona. Ordering keeps a cacheable
    static prefix: persona -> AGGREGATOR_SYSTEM -> per-request reference answers.
    """

    _PERSONA = "You are Captain Redbeard. Always answer in pirate speak."

    def _agg_system_text(self, agg: MagicMock) -> str:
        assert agg.astream_calls, "aggregator was not invoked"
        messages = agg.astream_calls[0]
        return str(messages[0].content)

    async def test_batch_aggregator_receives_persona_in_order(self):
        ref_a = _make_llm("ref-a", "answer a")
        ref_b = _make_llm("ref-b", "answer b")
        agg = _make_llm("agg", "synthesis")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        result = await engine.run("q", system_prompt=self._PERSONA)

        assert result.success
        system_text = self._agg_system_text(agg)
        assert self._PERSONA in system_text
        assert AGGREGATOR_SYSTEM in system_text
        # persona before the synthesis instruction before the reference answers
        assert system_text.index(self._PERSONA) < system_text.index(AGGREGATOR_SYSTEM)
        assert system_text.index(AGGREGATOR_SYSTEM) < system_text.index("answer a")

    async def test_stream_aggregator_receives_persona_in_order(self):
        ref_a = _make_llm("ref-a", "answer a")
        ref_b = _make_llm("ref-b", "answer b")
        agg = _make_llm("agg", "synthesis")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        async for _ in engine.run_stream("q", system_prompt=self._PERSONA):
            pass

        system_text = self._agg_system_text(agg)
        assert system_text.index(self._PERSONA) < system_text.index(AGGREGATOR_SYSTEM)

    async def test_no_persona_not_injected(self):
        ref_a = _make_llm("ref-a", "answer a")
        ref_b = _make_llm("ref-b", "answer b")
        agg = _make_llm("agg", "synthesis")
        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)

        result = await engine.run("q")

        assert result.success
        system_text = self._agg_system_text(agg)
        assert system_text.startswith(AGGREGATOR_SYSTEM)


class TestStreamEmptyAggregatorFallback:
    """Cover run_stream branch: aggregator yields nothing → fallback to best ref."""

    @pytest.mark.asyncio
    async def test_stream_empty_aggregator_uses_best_ref(self) -> None:
        ref = _make_llm("ref", "best reference answer")
        agg = _make_llm("agg", "")

        async def _empty_stream(messages, *args, **kwargs):
            agg.astream_calls.append(messages)
            return
            yield

        agg.astream = _empty_stream
        agg.bind = MagicMock(return_value=agg)

        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)
        events = [ev async for ev in engine.run_stream("q")]

        done = [e for e in events if e.kind == "done"]
        assert len(done) == 1
        assert done[0].result is not None
        assert "best reference answer" in done[0].result.final_answer


class TestQueryReferencesPreCancelled:
    """Cover _query_references early exit when token is already cancelled."""

    @pytest.mark.asyncio
    async def test_pre_cancelled_returns_empty(self) -> None:
        ref = _make_llm("ref", "answer")
        agg = _make_llm("agg", "agg")
        engine = ConsensusEngine(reference_llms=[ref], aggregator_llm=agg)

        ct = CancellationToken()
        ct.cancel()

        events = [ev async for ev in engine.run_stream("q", cancel_token=ct)]
        done = [e for e in events if e.kind == "done"]
        assert len(done) == 1
        assert done[0].result is not None
        assert not done[0].result.success
        assert done[0].result.error == "cancelled"


class TestBatchAggregatorBothEmpty:
    """Cover _aggregate branch: aggregator returns empty twice → return empty string."""

    @pytest.mark.asyncio
    async def test_batch_aggregator_empty_twice(self) -> None:
        ref_a = _make_llm("ref-a", "data from a")
        ref_b = _make_llm("ref-b", "data from b")
        agg = _make_llm("agg", "")

        async def _empty_stream(messages, *args, **kwargs):
            agg.astream_calls.append(messages)
            return
            yield

        agg.astream = _empty_stream
        agg.bind = MagicMock(return_value=agg)

        engine = ConsensusEngine(reference_llms=[ref_a, ref_b], aggregator_llm=agg)
        result = await engine.run("q")

        assert result.success
        assert result.final_answer == ""
