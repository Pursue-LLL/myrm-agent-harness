"""Output-cap recovery of ChatLiteLLM: provider-stated ``max_tokens`` limits.

Real provider wordings go through the real error classifier and the real retry loops of all four
entry points (sync/async x non-stream/stream). Only the provider client is faked, with genuine
litellm response objects. The recovery contract under test:

- a rejected request is retried with the limit the provider printed, and nothing else changes
  (so the provider-side prompt-prefix cache still hits);
- a model ceiling is remembered per endpoint, a window remainder is not;
- nothing is retried once the consumer has already received streamed output.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock

import litellm
import pytest
from langchain_core.messages import HumanMessage
from litellm.types.utils import Choices, Delta, Message, ModelResponse, ModelResponseStream, StreamingChoices

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM, output_cap_recovery
from myrm_agent_harness.toolkits.llms.adapters.chat_model.output_cap_recovery import (
    apply_learned_output_cap,
    recover_output_cap,
)
from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    get_ephemeral_max_output_tokens,
    reset_ephemeral_max_output_tokens,
    set_ephemeral_max_output_tokens,
)

MODEL = "openai/capped-model"
REQUESTED = 16384
CEILING = 8192

# DashScope wording of a model ceiling.
CEILING_ERROR = f"Range of max_tokens should be [1, {CEILING}]"
# Anthropic wording of a window remainder: 198000 prompt tokens leave 2000 of a 200000 window.
WINDOW_ERROR = (
    "input length and max_tokens exceed context limit: 198000 + 16384 > 200000, "
    "decrease input length or max_tokens and try again"
)
WINDOW_ERROR_NO_ROOM = WINDOW_ERROR.replace("198000", "199800")
WINDOW_REMAINDER_RETRY = 2000 - 64

MESSAGES = [HumanMessage(content="hi")]
SYNC_PATHS = ("generate", "stream")
ASYNC_PATHS = ("agenerate", "astream")


@pytest.fixture(autouse=True)
def _isolated_ceiling_memo() -> Iterator[None]:
    """The learned-ceiling memo is process-wide; every test starts and ends with it empty."""
    saved = dict(output_cap_recovery._LEARNED_CEILINGS)
    output_cap_recovery._LEARNED_CEILINGS.clear()
    reset_ephemeral_max_output_tokens()
    yield
    output_cap_recovery._LEARNED_CEILINGS.clear()
    output_cap_recovery._LEARNED_CEILINGS.update(saved)
    reset_ephemeral_max_output_tokens()


def _bad_request(message: str) -> Exception:
    return litellm.exceptions.BadRequestError(message=message, model=MODEL, llm_provider="openai")


def _rate_limited(message: str) -> Exception:
    return litellm.exceptions.RateLimitError(message=message, model=MODEL, llm_provider="openai")


def _model(**kwargs: object) -> ChatLiteLLM:
    model = ChatLiteLLM(model=MODEL, max_tokens=REQUESTED, **kwargs)
    model.client = MagicMock()
    return model


def _delta(text: str, finish_reason: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        choices=[StreamingChoices(delta=Delta(content=text, role="assistant"), finish_reason=finish_reason)]
    )


def _sync_stream(*, fail_with: Exception | None = None, after: int = 0) -> Iterator[ModelResponseStream]:
    """Yield ``after`` chunks of 'Hello', then raise ``fail_with`` or finish normally."""
    for _ in range(after):
        yield _delta("Hello")
    if fail_with is not None:
        raise fail_with
    yield _delta("ok", "stop")


async def _async_stream(*, fail_with: Exception | None = None, after: int = 0) -> AsyncIterator[ModelResponseStream]:
    for _ in range(after):
        yield _delta("Hello")
    if fail_with is not None:
        raise fail_with
    yield _delta("ok", "stop")


def _success(path: str) -> object:
    if path in ("generate", "agenerate"):
        return ModelResponse(choices=[Choices(message=Message(role="assistant", content="ok"), finish_reason="stop")])
    return _sync_stream() if path == "stream" else _async_stream()


def _script(model: ChatLiteLLM, path: str, *outcomes: object) -> MagicMock:
    """Install the provider fake for ``path``: exceptions are raised, the string 'ok' becomes a normal response."""
    resolved = [_success(path) if outcome == "ok" else outcome for outcome in outcomes]
    if path in ASYNC_PATHS:
        model.client.acreate = AsyncMock(side_effect=resolved)
        return model.client.acreate
    model.client.completion = MagicMock(side_effect=resolved)
    return model.client.completion


def _run_sync(model: ChatLiteLLM, path: str) -> str:
    if path == "generate":
        return str(model._generate(MESSAGES).generations[0].message.content)
    return "".join(str(chunk.message.content) for chunk in model._stream(MESSAGES))


async def _run_async(model: ChatLiteLLM, path: str) -> str:
    if path == "agenerate":
        return str((await model._agenerate(MESSAGES)).generations[0].message.content)
    return "".join([str(chunk.message.content) async for chunk in model._astream(MESSAGES)])


def _max_tokens_sent(client: MagicMock) -> list[int]:
    return [call.kwargs["max_tokens"] for call in client.call_args_list]


def _assert_only_max_tokens_differs(client: MagicMock) -> None:
    """The retry must keep messages, tools and thinking parameters identical so the provider's prompt cache hits."""
    first, second = (call.kwargs for call in client.call_args_list)
    assert {k: v for k, v in first.items() if k != "max_tokens"} == {
        k: v for k, v in second.items() if k != "max_tokens"
    }


class TestRetryLoops:
    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_sync_model_ceiling_is_retried_with_only_max_tokens_lowered(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(CEILING_ERROR), "ok")

        assert _run_sync(model, path) == "ok"

        assert _max_tokens_sent(client) == [REQUESTED, CEILING]
        _assert_only_max_tokens_differs(client)

    @pytest.mark.parametrize("path", ASYNC_PATHS)
    async def test_async_model_ceiling_is_retried_with_only_max_tokens_lowered(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(CEILING_ERROR), "ok")

        assert await _run_async(model, path) == "ok"

        assert _max_tokens_sent(client) == [REQUESTED, CEILING]
        _assert_only_max_tokens_differs(client)

    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_sync_next_request_starts_at_the_learned_ceiling(self, path: str) -> None:
        first = _model()
        _script(first, path, _bad_request(CEILING_ERROR), "ok")
        _run_sync(first, path)

        later = _model()
        client = _script(later, path, "ok")
        assert _run_sync(later, path) == "ok"

        assert _max_tokens_sent(client) == [CEILING]

    @pytest.mark.parametrize("path", ASYNC_PATHS)
    async def test_async_next_request_starts_at_the_learned_ceiling(self, path: str) -> None:
        first = _model()
        _script(first, path, _bad_request(CEILING_ERROR), "ok")
        await _run_async(first, path)

        later = _model()
        client = _script(later, path, "ok")
        assert await _run_async(later, path) == "ok"

        assert _max_tokens_sent(client) == [CEILING]

    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_sync_window_remainder_keeps_a_margin_and_is_not_remembered(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(WINDOW_ERROR), "ok")
        assert _run_sync(model, path) == "ok"
        assert _max_tokens_sent(client) == [REQUESTED, WINDOW_REMAINDER_RETRY]

        # The remainder belongs to that one request; a shorter prompt later gets the full budget again.
        later = _model()
        client = _script(later, path, "ok")
        _run_sync(later, path)
        assert _max_tokens_sent(client) == [REQUESTED]

    @pytest.mark.parametrize("path", ASYNC_PATHS)
    async def test_async_window_remainder_keeps_a_margin_and_is_not_remembered(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(WINDOW_ERROR), "ok")
        assert await _run_async(model, path) == "ok"
        assert _max_tokens_sent(client) == [REQUESTED, WINDOW_REMAINDER_RETRY]

        later = _model()
        client = _script(later, path, "ok")
        await _run_async(later, path)
        assert _max_tokens_sent(client) == [REQUESTED]

    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_sync_remainder_too_small_to_answer_fails_fast_for_compression(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(WINDOW_ERROR_NO_ROOM), "ok")

        with pytest.raises(litellm.exceptions.BadRequestError):
            _run_sync(model, path)

        assert client.call_count == 1

    @pytest.mark.parametrize("path", ASYNC_PATHS)
    async def test_async_remainder_too_small_to_answer_fails_fast_for_compression(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(WINDOW_ERROR_NO_ROOM), "ok")

        with pytest.raises(litellm.exceptions.BadRequestError):
            await _run_async(model, path)

        assert client.call_count == 1

    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_sync_ceiling_that_would_not_lower_the_request_is_not_retried(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _bad_request(f"Range of max_tokens should be [1, {REQUESTED * 2}]"), "ok")

        with pytest.raises(litellm.exceptions.BadRequestError):
            _run_sync(model, path)

        assert client.call_count == 1

    @pytest.mark.parametrize("path", ASYNC_PATHS)
    async def test_async_rate_limit_with_similar_wording_is_not_retried(self, path: str) -> None:
        model = _model()
        client = _script(model, path, _rate_limited(CEILING_ERROR), "ok")

        with pytest.raises(litellm.exceptions.RateLimitError):
            await _run_async(model, path)

        assert client.call_count == 1

    @pytest.mark.parametrize("path", SYNC_PATHS)
    def test_learned_ceiling_applies_after_the_truncation_boost_override(self, path: str) -> None:
        first = _model()
        _script(first, path, _bad_request(CEILING_ERROR), "ok")
        _run_sync(first, path)

        later = _model()
        client = _script(later, path, "ok")
        set_ephemeral_max_output_tokens(REQUESTED * 2)
        _run_sync(later, path)

        assert _max_tokens_sent(client) == [CEILING]
        assert get_ephemeral_max_output_tokens() is None


class TestNothingIsRetriedOnceStreamingStarted:
    """A retry restarts the stream; after the consumer received output it would duplicate that output."""

    MID_STREAM_ERRORS = (
        pytest.param(_bad_request(CEILING_ERROR), id="model-ceiling"),
        pytest.param(_bad_request(WINDOW_ERROR), id="window-remainder"),
        pytest.param(Exception("Unsupported parameter: 'stream_options'"), id="gateway-param"),
    )

    @pytest.mark.parametrize("error", MID_STREAM_ERRORS)
    def test_sync_error_after_streamed_output_propagates_without_a_restart(self, error: Exception) -> None:
        model = _model()
        client = _script(model, "stream", _sync_stream(fail_with=error, after=1), "ok")
        received: list[str] = []

        with pytest.raises(type(error)):
            for chunk in model._stream(MESSAGES):
                received.append(str(chunk.message.content))

        assert received == ["Hello"]
        assert client.call_count == 1

    @pytest.mark.parametrize("error", MID_STREAM_ERRORS)
    async def test_async_error_after_streamed_output_propagates_without_a_restart(self, error: Exception) -> None:
        model = _model()
        client = _script(model, "astream", _async_stream(fail_with=error, after=1), "ok")
        received: list[str] = []

        with pytest.raises(type(error)):
            async for chunk in model._astream(MESSAGES):
                received.append(str(chunk.message.content))

        assert received == ["Hello"]
        assert client.call_count == 1

    def test_sync_error_before_the_first_chunk_is_still_recovered(self) -> None:
        model = _model()
        client = _script(model, "stream", _sync_stream(fail_with=_bad_request(CEILING_ERROR)), "ok")

        assert _run_sync(model, "stream") == "ok"
        assert _max_tokens_sent(client) == [REQUESTED, CEILING]

    async def test_async_error_before_the_first_chunk_is_still_recovered(self) -> None:
        model = _model()
        client = _script(model, "astream", _async_stream(fail_with=_bad_request(CEILING_ERROR)), "ok")

        assert await _run_async(model, "astream") == "ok"
        assert _max_tokens_sent(client) == [REQUESTED, CEILING]


class TestRecoverOutputCap:
    def test_model_ceiling_is_adopted_as_stated_and_remembered(self) -> None:
        params: dict[str, object] = {"max_tokens": REQUESTED}

        assert recover_output_cap(_bad_request(CEILING_ERROR), params, model=MODEL, base_url="")

        assert params["max_tokens"] == CEILING
        later: dict[str, object] = {"max_tokens": REQUESTED}
        apply_learned_output_cap(later, model=MODEL, base_url="")
        assert later["max_tokens"] == CEILING

    def test_unset_max_tokens_adopts_the_stated_ceiling(self) -> None:
        params: dict[str, object] = {}

        assert recover_output_cap(_bad_request(CEILING_ERROR), params, model=MODEL, base_url="")

        assert params["max_tokens"] == CEILING

    @pytest.mark.parametrize("status_error", (_rate_limited(CEILING_ERROR),), ids=("429",))
    def test_statuses_that_never_carry_an_output_limit_are_refused(self, status_error: Exception) -> None:
        params: dict[str, object] = {"max_tokens": REQUESTED}

        assert not recover_output_cap(status_error, params, model=MODEL, base_url="")

        assert params["max_tokens"] == REQUESTED

    def test_error_without_a_status_is_still_read(self) -> None:
        params: dict[str, object] = {"max_tokens": REQUESTED}

        assert recover_output_cap(Exception(CEILING_ERROR), params, model=MODEL, base_url="")

        assert params["max_tokens"] == CEILING

    def test_unrecognised_error_leaves_the_request_untouched(self) -> None:
        params: dict[str, object] = {"max_tokens": REQUESTED}

        assert not recover_output_cap(_bad_request("messages: roles must alternate"), params, model=MODEL, base_url="")

        assert params == {"max_tokens": REQUESTED}

    @pytest.mark.parametrize(
        "params",
        (
            pytest.param(
                {"max_tokens": REQUESTED, "thinking": {"type": "enabled", "budget_tokens": CEILING}}, id="top-level"
            ),
            pytest.param(
                {
                    "max_tokens": REQUESTED,
                    "extra_body": {"thinking": {"type": "enabled", "budget_tokens": CEILING + 1}},
                },
                id="extra-body",
            ),
        ),
    )
    def test_ceiling_without_room_for_the_thinking_budget_is_refused(self, params: dict[str, object]) -> None:
        before = dict(params)

        assert not recover_output_cap(_bad_request(CEILING_ERROR), params, model=MODEL, base_url="")

        assert params == before
        assert not output_cap_recovery._LEARNED_CEILINGS

    def test_ceiling_with_room_for_the_thinking_budget_is_adopted(self) -> None:
        params: dict[str, object] = {
            "max_tokens": REQUESTED,
            "thinking": {"type": "enabled", "budget_tokens": CEILING // 2},
        }

        assert recover_output_cap(_bad_request(CEILING_ERROR), params, model=MODEL, base_url="")

        assert params["max_tokens"] == CEILING

    def test_memo_is_bounded_and_evicts_the_oldest_endpoint_first(self) -> None:
        limit = output_cap_recovery._LEARNED_CEILINGS_MAX
        for index in range(limit + 44):
            recover_output_cap(
                _bad_request(CEILING_ERROR), {"max_tokens": REQUESTED}, model=f"{MODEL}-{index}", base_url=""
            )

        assert len(output_cap_recovery._LEARNED_CEILINGS) == limit
        assert (f"{MODEL}-0", "") not in output_cap_recovery._LEARNED_CEILINGS
        assert (f"{MODEL}-{limit + 43}", "") in output_cap_recovery._LEARNED_CEILINGS


class TestApplyLearnedOutputCap:
    @staticmethod
    def _learn(*, model: str = MODEL, base_url: str = "", expires_in: float = 60.0) -> None:
        output_cap_recovery._LEARNED_CEILINGS[(model.lower(), base_url.lower())] = (
            CEILING,
            time.monotonic() + expires_in,
        )

    def test_lowers_a_request_above_the_ceiling(self) -> None:
        self._learn()
        params: dict[str, object] = {"max_tokens": REQUESTED}

        apply_learned_output_cap(params, model=MODEL, base_url="")

        assert params["max_tokens"] == CEILING

    def test_never_raises_or_invents_a_budget(self) -> None:
        self._learn()
        lower: dict[str, object] = {"max_tokens": CEILING // 2}
        unset: dict[str, object] = {}

        apply_learned_output_cap(lower, model=MODEL, base_url="")
        apply_learned_output_cap(unset, model=MODEL, base_url="")

        assert lower == {"max_tokens": CEILING // 2}
        assert unset == {}

    def test_other_endpoints_are_untouched(self) -> None:
        self._learn(base_url="https://gateway-a.example/v1")
        params: dict[str, object] = {"max_tokens": REQUESTED}

        apply_learned_output_cap(params, model=MODEL, base_url="https://gateway-b.example/v1")

        assert params["max_tokens"] == REQUESTED

    def test_endpoint_key_ignores_case(self) -> None:
        self._learn(model=MODEL.upper(), base_url="HTTPS://Gateway.example/v1")
        params: dict[str, object] = {"max_tokens": REQUESTED}

        apply_learned_output_cap(params, model=MODEL, base_url="https://gateway.example/v1")

        assert params["max_tokens"] == CEILING

    def test_expired_ceiling_is_dropped_so_a_raised_provider_limit_is_picked_up(self) -> None:
        self._learn(expires_in=-1.0)
        params: dict[str, object] = {"max_tokens": REQUESTED}

        apply_learned_output_cap(params, model=MODEL, base_url="")

        assert params["max_tokens"] == REQUESTED
        assert not output_cap_recovery._LEARNED_CEILINGS
