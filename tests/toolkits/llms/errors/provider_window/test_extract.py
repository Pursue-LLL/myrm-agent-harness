"""Provider-window extractor: precedence, classification, rejection of unusable values."""

from __future__ import annotations

import json

import httpx
import pytest

from myrm_agent_harness.toolkits.llms.errors.provider_window import (
    HOLD_MAX_S,
    IN_TURN_WAIT_MAX_S,
    WindowKind,
    WindowSource,
    extract_provider_window,
    has_rejected_quota_window,
)

NOW = 1_800_000_000.0


class _ProviderError(Exception):
    def __init__(
        self,
        message: str = "rate limited",
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.response = httpx.Response(429, headers=headers or {}, content=json.dumps(body or {}).encode())
        self.body = body


def _chained(inner: BaseException, depth: int) -> Exception:
    """Wrap *inner* in *depth* outer exceptions the way litellm wraps SDK errors."""
    current: BaseException = inner
    for level in range(depth):
        outer = RuntimeError(f"wrapper {level}")
        outer.__cause__ = current
        current = outer
    assert isinstance(current, Exception)
    return current


def _anthropic_headers(**windows: tuple[str, int | None]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, (status, reset) in windows.items():
        headers[f"anthropic-ratelimit-unified-{name}-status"] = status
        if reset is not None:
            headers[f"anthropic-ratelimit-unified-{name}-reset"] = str(reset)
    return headers


class TestAnthropicUnified:
    def test_five_hour_window_rejected(self) -> None:
        exc = _ProviderError(headers=_anthropic_headers(**{"5h": ("rejected", int(NOW) + 3600)}))

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.ANTHROPIC_UNIFIED
        assert hint.quota_window is True
        assert hint.reset_at == NOW + 3600
        assert hint.kind is WindowKind.HOLD

    def test_multiple_rejected_windows_take_the_latest_reset(self) -> None:
        exc = _ProviderError(
            headers=_anthropic_headers(
                **{"5h": ("rejected", int(NOW) + 3600), "7d": ("rejected", int(NOW) + 3 * 86400)}
            )
        )

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.wait_s == 3 * 86400
        assert hint.kind is WindowKind.BEYOND

    def test_allowed_window_is_not_a_boundary(self) -> None:
        headers = _anthropic_headers(**{"5h": ("rejected", int(NOW) + 600), "7d": ("allowed", int(NOW) + 5 * 86400)})

        hint = extract_provider_window(_ProviderError(headers=headers), now=NOW)

        assert hint is not None
        assert hint.wait_s == 600

    def test_rejected_window_without_reset_yields_no_hint_and_ignores_retry_after(self) -> None:
        headers = {**_anthropic_headers(**{"7d": ("rejected", None)}), "retry-after": "30"}
        exc = _ProviderError(headers=headers)

        assert extract_provider_window(exc, now=NOW) is None
        assert has_rejected_quota_window(exc) is True

    def test_one_rejected_window_missing_reset_invalidates_the_hint(self) -> None:
        headers = _anthropic_headers(**{"5h": ("rejected", int(NOW) + 600), "7d": ("rejected", None)})

        assert extract_provider_window(_ProviderError(headers=headers), now=NOW) is None

    def test_stale_reset_is_unusable(self) -> None:
        exc = _ProviderError(headers=_anthropic_headers(**{"5h": ("rejected", int(NOW) - 10)}))

        assert extract_provider_window(exc, now=NOW) is None

    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    def test_headers_are_found_at_any_chain_depth(self, depth: int) -> None:
        inner = _ProviderError(headers=_anthropic_headers(**{"5h": ("rejected", int(NOW) + 900)}))

        hint = extract_provider_window(_chained(inner, depth), now=NOW)

        assert hint is not None
        assert hint.wait_s == 900

    def test_no_rejected_window_means_no_quota_signal(self) -> None:
        exc = _ProviderError(headers=_anthropic_headers(**{"5h": ("allowed", int(NOW) + 900)}))

        assert has_rejected_quota_window(exc) is False


class TestOverageIsNotAWindow:
    """``overage`` is the pay-as-you-go pool: it can be rejected while every quota window is open."""

    def test_rejected_overage_does_not_poison_a_spent_window(self) -> None:
        headers = _anthropic_headers(**{"5h": ("rejected", int(NOW) + 3600), "overage": ("rejected", None)})

        hint = extract_provider_window(_ProviderError(headers=headers), now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.ANTHROPIC_UNIFIED
        assert hint.reset_at == NOW + 3600

    def test_rejected_overage_alone_is_no_quota_signal(self) -> None:
        headers = _anthropic_headers(**{"5h": ("allowed", int(NOW) + 900), "overage": ("rejected", int(NOW) + 86400)})
        exc = _ProviderError(headers=headers)

        assert has_rejected_quota_window(exc) is False
        assert extract_provider_window(exc, now=NOW) is None

    def test_rejected_overage_leaves_retry_after_usable(self) -> None:
        headers = {**_anthropic_headers(overage=("rejected", None)), "retry-after": "30"}

        hint = extract_provider_window(_ProviderError(headers=headers), now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.RETRY_AFTER
        assert hint.quota_window is False


class TestCodexBody:
    def test_resets_at_is_absolute(self) -> None:
        body = {"error": {"type": "usage_limit_reached", "resets_at": int(NOW) + 7200, "resets_in_seconds": 1}}

        hint = extract_provider_window(_ProviderError(body=body), now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.CODEX_BODY
        assert hint.quota_window is True
        assert hint.wait_s == 7200

    def test_resets_in_seconds_is_relative_to_now(self) -> None:
        hint = extract_provider_window(_ProviderError(body={"resets_in_seconds": 120}), now=NOW)

        assert hint is not None
        assert hint.reset_at == NOW + 120
        assert hint.kind is WindowKind.IN_TURN

    def test_past_resets_at_falls_back_to_resets_in_seconds(self) -> None:
        body = {"resets_at": int(NOW) - 5, "resets_in_seconds": 90}

        hint = extract_provider_window(_ProviderError(body=body), now=NOW)

        assert hint is not None
        assert hint.wait_s == 90

    @pytest.mark.parametrize("value", [True, "3600", -1, 0, float("inf"), float("nan")])
    def test_non_numeric_or_non_positive_values_are_ignored(self, value: object) -> None:
        assert extract_provider_window(_ProviderError(body={"resets_in_seconds": value}), now=NOW) is None

    def test_millisecond_epoch_is_rejected_as_implausible(self) -> None:
        body = {"resets_at": (int(NOW) + 3600) * 1000}

        assert extract_provider_window(_ProviderError(body=body), now=NOW) is None

    def test_weekly_window_is_beyond_hold(self) -> None:
        hint = extract_provider_window(_ProviderError(body={"resets_in_seconds": 5 * 86400}), now=NOW)

        assert hint is not None
        assert hint.kind is WindowKind.BEYOND


class TestRetryAfter:
    @pytest.mark.parametrize(("raw", "expected"), [("15", 15.0), ("30.5", 30.5), ("1", 1.0)])
    def test_numeric_seconds(self, raw: str, expected: float) -> None:
        hint = extract_provider_window(_ProviderError(headers={"Retry-After": raw}), now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.RETRY_AFTER
        assert hint.quota_window is False
        assert hint.wait_s == expected

    def test_http_date(self) -> None:
        # 1_800_000_000 == Fri, 15 Jan 2027 08:00:00 GMT
        hint = extract_provider_window(
            _ProviderError(headers={"Retry-After": "Fri, 15 Jan 2027 08:05:00 GMT"}), now=NOW
        )

        assert hint is not None
        assert hint.wait_s == 300
        assert hint.kind is WindowKind.IN_TURN

    @pytest.mark.parametrize("raw", ["", "abc", "-5", "0", "inf", "nan", "Fri, 15 Jan 2027 07:00:00 GMT"])
    def test_invalid_or_past_values(self, raw: str) -> None:
        assert extract_provider_window(_ProviderError(headers={"Retry-After": raw}), now=NOW) is None

    def test_value_beyond_a_year_is_implausible(self) -> None:
        assert extract_provider_window(_ProviderError(headers={"Retry-After": str(10**9)}), now=NOW) is None

    def test_plain_dict_headers_attribute(self) -> None:
        exc = Exception("rate limited")
        exc.headers = {"retry-after": "20"}  # type: ignore[attr-defined]

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.wait_s == 20

    def test_response_headers_attribute(self) -> None:
        exc = Exception("rate limited")
        exc.response_headers = {"Retry-After": "25"}  # type: ignore[attr-defined]

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.wait_s == 25


class TestMessageText:
    def test_retry_after_seconds_in_message(self) -> None:
        hint = extract_provider_window(Exception("Please retry after 45 seconds"), now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.MESSAGE
        assert hint.wait_s == 45

    @pytest.mark.parametrize("message", ["billing error", "authentication failed", "Unknown error occurred"])
    def test_unrelated_messages_yield_nothing(self, message: str) -> None:
        assert extract_provider_window(Exception(message), now=NOW) is None


class TestPrecedence:
    def test_header_beats_message(self) -> None:
        exc = _ProviderError("retry after 999 seconds", headers={"Retry-After": "10"})

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.RETRY_AFTER
        assert hint.wait_s == 10

    def test_body_window_beats_retry_after(self) -> None:
        exc = _ProviderError(headers={"Retry-After": "5"}, body={"resets_in_seconds": 7200})

        hint = extract_provider_window(exc, now=NOW)

        assert hint is not None
        assert hint.source is WindowSource.CODEX_BODY

    def test_outer_header_wins_over_inner(self) -> None:
        inner = _ProviderError(headers={"Retry-After": "100"})
        outer = _ProviderError(headers={"Retry-After": "7"})
        outer.__cause__ = inner

        hint = extract_provider_window(outer, now=NOW)

        assert hint is not None
        assert hint.wait_s == 7


class TestKindBoundaries:
    @pytest.mark.parametrize(
        ("wait_s", "kind"),
        [
            (1, WindowKind.IN_TURN),
            (IN_TURN_WAIT_MAX_S, WindowKind.IN_TURN),
            (IN_TURN_WAIT_MAX_S + 1, WindowKind.HOLD),
            (HOLD_MAX_S, WindowKind.HOLD),
            (HOLD_MAX_S + 1, WindowKind.BEYOND),
        ],
    )
    def test_boundaries(self, wait_s: float, kind: WindowKind) -> None:
        hint = extract_provider_window(_ProviderError(body={"resets_in_seconds": wait_s}), now=NOW)

        assert hint is not None
        assert hint.kind is kind


def test_cyclic_chain_terminates() -> None:
    a = Exception("a")
    b = Exception("b")
    a.__cause__ = b
    b.__cause__ = a

    assert extract_provider_window(a, now=NOW) is None
