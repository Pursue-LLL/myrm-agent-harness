"""Extractor and classifier against exceptions raised by the real litellm transport.

A local HTTP server answers with the header/body shapes of the Anthropic subscription route
and the Codex route; litellm wraps them exactly as it does in production.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
litellm = pytest.importorskip("litellm")

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error
from myrm_agent_harness.toolkits.llms.errors.provider_window import (
    WindowKind,
    WindowSource,
    extract_provider_window,
    has_rejected_quota_window,
)


class _Handler(BaseHTTPRequestHandler):
    status = 429
    headers_out: ClassVar[dict[str, str]] = {}
    body: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.dumps(self.body).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in self.headers_out.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def provider() -> Iterator[tuple[type[_Handler], str]]:
    _Handler.status, _Handler.headers_out, _Handler.body = 429, {}, {}
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Handler, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _call(model: str, base: str) -> Exception:
    with pytest.raises(Exception) as caught:
        litellm.completion(
            model=model,
            api_base=base,
            api_key="test-key",
            messages=[{"role": "user", "content": "hi"}],
            num_retries=0,
            max_tokens=8,
        )
    return caught.value


def test_anthropic_subscription_five_hour_window(provider: tuple[type[_Handler], str]) -> None:
    handler, base = provider
    reset = int(time.time()) + 3 * 3600
    handler.headers_out = {
        "anthropic-ratelimit-unified-status": "rejected",
        "anthropic-ratelimit-unified-5h-status": "rejected",
        "anthropic-ratelimit-unified-5h-reset": str(reset),
        "anthropic-ratelimit-unified-7d-status": "allowed",
        "anthropic-ratelimit-unified-7d-reset": str(reset + 4 * 86400),
        "retry-after": "30",
    }
    handler.body = {"type": "error", "error": {"type": "rate_limit_error", "message": "usage limit"}}

    exc = _call("anthropic/claude-sonnet-4-5", base)
    hint = extract_provider_window(exc)

    assert has_rejected_quota_window(exc)
    assert hint is not None
    assert hint.source is WindowSource.ANTHROPIC_UNIFIED
    assert hint.reset_at == reset
    assert hint.kind is WindowKind.HOLD


def test_codex_usage_limit_body(provider: tuple[type[_Handler], str]) -> None:
    handler, base = provider
    handler.headers_out = {}
    handler.body = {
        "error": {
            "type": "usage_limit_reached",
            "message": "The usage limit has been reached",
            "resets_in_seconds": 5400,
        }
    }

    exc = _call("openai/gpt-5", base)
    hint = extract_provider_window(exc)

    assert hint is not None
    assert hint.source is WindowSource.CODEX_BODY
    assert hint.quota_window
    assert 5390 < hint.wait_s <= 5400


def test_plain_retry_after_header(provider: tuple[type[_Handler], str]) -> None:
    handler, base = provider
    handler.headers_out = {"Retry-After": "42"}
    handler.body = {"error": {"type": "rate_limit_error", "message": "slow down"}}

    hint = extract_provider_window(_call("openai/gpt-5", base))

    assert hint is not None
    assert hint.source is WindowSource.RETRY_AFTER
    assert 41 < hint.wait_s <= 42
    assert hint.kind is WindowKind.IN_TURN


def test_429_without_any_window_signal(provider: tuple[type[_Handler], str]) -> None:
    handler, base = provider
    handler.headers_out = {}
    handler.body = {"error": {"type": "rate_limit_error", "message": "slow down"}}

    exc = _call("openai/gpt-5", base)

    assert extract_provider_window(exc) is None
    assert not has_rejected_quota_window(exc)


# Header sets transcribed from public captures of subscription responses (anthropics/claude-code#59974):
# an account whose pay-as-you-go pool is disabled reports it as rejected on every response.
_OVERAGE_DISABLED = {
    "anthropic-ratelimit-unified-overage-status": "rejected",
    "anthropic-ratelimit-unified-overage-disabled-reason": "out_of_credits",
}


def _windows(now: int, *, five_hour: str) -> dict[str, str]:
    return {
        "anthropic-ratelimit-unified-status": "rejected" if five_hour == "rejected" else "allowed",
        "anthropic-ratelimit-unified-5h-status": five_hour,
        "anthropic-ratelimit-unified-5h-reset": str(now + 3600),
        "anthropic-ratelimit-unified-7d-status": "allowed",
        "anthropic-ratelimit-unified-7d-reset": str(now + 5 * 86400),
    }


def test_spent_window_is_held_even_when_the_overage_pool_is_disabled(provider: tuple[type[_Handler], str]) -> None:
    handler, base = provider
    now = int(time.time())
    handler.headers_out = {**_windows(now, five_hour="rejected"), **_OVERAGE_DISABLED}
    handler.body = {"type": "error", "error": {"type": "rate_limit_error", "message": "usage limit"}}

    exc = _call("anthropic/claude-sonnet-4-5", base)
    hint = extract_provider_window(exc)

    assert hint is not None
    assert hint.source is WindowSource.ANTHROPIC_UNIFIED
    assert hint.reset_at == now + 3600
    assert hint.kind is WindowKind.HOLD
    assert classify_error(exc) is ErrorKind.BILLING


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
        (500, {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}),
        (
            400,
            {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "prompt is too long: 250000 tokens > 200000"},
            },
        ),
    ],
)
def test_disabled_overage_pool_never_reclassifies_unrelated_errors(
    provider: tuple[type[_Handler], str], status: int, body: dict[str, object]
) -> None:
    handler, base = provider
    now = int(time.time())
    handler.status, handler.body = status, body

    handler.headers_out = _windows(now, five_hour="allowed")
    expected = classify_error(_call("anthropic/claude-sonnet-4-5", base))

    handler.headers_out = {**_windows(now, five_hour="allowed"), **_OVERAGE_DISABLED}
    exc = _call("anthropic/claude-sonnet-4-5", base)

    assert classify_error(exc) is expected
    assert expected is not ErrorKind.BILLING
    assert not has_rejected_quota_window(exc)
    assert extract_provider_window(exc) is None
