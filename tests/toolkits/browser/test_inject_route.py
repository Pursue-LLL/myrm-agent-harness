"""Unit tests for enhancers.inject_route (document-response script injection).

Real-Chromium behavior (redirect hops, single request per document, downloads, compression) is
proven in ``test_document_redirect_integration.py``; these tests pin the handler's decisions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.enhancers.inject_route import (
    _inject_handler,
    install_document_script_injection,
)


def _make_route(
    resource_type: str = "document",
    content_type: str = "text/html",
    body: bytes | None = None,
    status: int = 200,
) -> tuple[MagicMock, MagicMock]:
    """Build (route, response) mimicking patchright primitives."""
    if body is None:
        body = b"<html><head><title>base</title></head><body></body></html>"
    route = MagicMock()
    route.request.resource_type = resource_type
    route.fallback = AsyncMock()
    route.fulfill = AsyncMock()
    route.fetch = AsyncMock()
    response = MagicMock()
    response.status = status
    response.headers = {"content-type": content_type}
    response.body = AsyncMock(return_value=body)
    route.fetch.return_value = response
    return route, response


def _assert_fulfilled_untouched(route: MagicMock, response: MagicMock) -> None:
    """The fetched response is passed on as-is, from the one request already made."""
    route.fulfill.assert_awaited_once_with(response=response)
    route.fallback.assert_not_called()
    route.fetch.assert_awaited_once()


class TestInjectHandler:
    @pytest.mark.asyncio
    async def test_document_html_gets_script_injected(self) -> None:
        route, response = _make_route()
        await _inject_handler(route, [lambda: "console.log(1)"])
        route.fetch.assert_awaited_once()
        route.fallback.assert_not_called()
        kwargs = route.fulfill.await_args.kwargs
        assert kwargs["response"] is response
        assert b"<script>console.log(1)</script>" in kwargs["body"]
        assert b"</head>" in kwargs["body"]

    @pytest.mark.asyncio
    async def test_redirects_are_never_followed_by_the_route(self) -> None:
        route, _ = _make_route()
        await _inject_handler(route, [lambda: "A()"])
        route.fetch.assert_awaited_once_with(max_redirects=0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    async def test_redirect_responses_pass_through_without_reading_the_body(self, status: int) -> None:
        route, response = _make_route(status=status)
        await _inject_handler(route, [lambda: "A()"])
        _assert_fulfilled_untouched(route, response)
        response.body.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_status_html_still_gets_the_script(self) -> None:
        route, _ = _make_route(status=404)
        await _inject_handler(route, [lambda: "A()"])
        assert b"<script>A()</script>" in route.fulfill.await_args.kwargs["body"]

    @pytest.mark.asyncio
    async def test_multiple_providers_all_injected_once(self) -> None:
        route, _ = _make_route()
        await _inject_handler(route, [lambda: "A()", lambda: "B()"])
        body = route.fulfill.await_args.kwargs["body"]
        assert b"<script>A()</script><script>B()</script>" in body

    @pytest.mark.asyncio
    async def test_script_source_with_closing_tag_is_escaped(self) -> None:
        route, _ = _make_route()
        await _inject_handler(route, [lambda: 'document.write("</script><b>x</b>")'])
        body = route.fulfill.await_args.kwargs["body"]
        assert b"<\\/script>" in body
        assert b"</script><b>" not in body.replace(b"<\\/script>", b"")

    @pytest.mark.asyncio
    async def test_non_document_falls_through(self) -> None:
        route, _ = _make_route(resource_type="xhr")
        await _inject_handler(route, [lambda: "A()"])
        route.fetch.assert_not_called()
        route.fallback.assert_awaited_once()
        route.fulfill.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_html_is_fulfilled_from_the_same_request(self) -> None:
        route, response = _make_route(content_type="application/json")
        await _inject_handler(route, [lambda: "A()"])
        _assert_fulfilled_untouched(route, response)
        response.body.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_body_is_fulfilled_untouched(self) -> None:
        route, response = _make_route(body=b"")
        await _inject_handler(route, [lambda: "A()"])
        _assert_fulfilled_untouched(route, response)

    @pytest.mark.asyncio
    async def test_no_head_tag_prepends_to_body(self) -> None:
        route, _ = _make_route(body=b"<html><body>x</body></html>")
        await _inject_handler(route, [lambda: "A()"])
        assert route.fulfill.await_args.kwargs["body"].startswith(b"<script>A()</script>")

    @pytest.mark.asyncio
    async def test_fetch_error_never_blocks_navigation(self) -> None:
        route, _ = _make_route()
        route.fetch = AsyncMock(side_effect=RuntimeError("network gone"))
        await _inject_handler(route, [lambda: "A()"])
        route.fallback.assert_awaited_once()
        route.fulfill.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_utf8_charset_roundtrip(self) -> None:
        """gbk page: injected script stays intact, original bytes preserved."""
        route, _ = _make_route(
            content_type="text/html; charset=gbk",
            body="<html><head><title>页</title></head><body>中文</body></html>".encode("gbk"),
        )
        await _inject_handler(route, [lambda: "mark()"])
        body = route.fulfill.await_args.kwargs["body"]
        assert b"<script>mark()</script>" in body.decode("gbk").encode()
        assert body.decode("gbk").endswith("</body></html>")

    @pytest.mark.asyncio
    async def test_undeclared_charset_invalid_bytes_are_fulfilled_untouched(self) -> None:
        route, response = _make_route(
            content_type="text/html",
            body=b"<html><head></head><body>\xff\xfe</body></html>",
        )
        await _inject_handler(route, [lambda: "A()"])
        _assert_fulfilled_untouched(route, response)

    @pytest.mark.asyncio
    async def test_no_providers_document_falls_through_without_a_request(self) -> None:
        """Nothing to inject: the browser makes the one request and later route handlers still run."""
        route, _ = _make_route(resource_type="document")
        await _inject_handler(route, [])
        route.fallback.assert_awaited_once()
        route.fetch.assert_not_called()
        route.fulfill.assert_not_called()


class _StubContext:
    """Minimal context stub without MagicMock auto-attribute magic."""

    def __init__(self) -> None:
        self.route_calls: list[tuple[object, ...]] = []

    async def route(self, *args: object) -> None:
        self.route_calls.append(args)


class TestInstall:
    @pytest.mark.asyncio
    async def test_first_call_installs_single_handler(self) -> None:
        ctx = _StubContext()
        await install_document_script_injection(ctx, lambda: "A()", label="a")  # type: ignore[arg-type]
        assert len(ctx.route_calls) == 1

    @pytest.mark.asyncio
    async def test_second_call_accumulates_provider_without_new_handler(self) -> None:
        ctx = _StubContext()
        await install_document_script_injection(ctx, lambda: "A()", label="a")  # type: ignore[arg-type]
        await install_document_script_injection(ctx, lambda: "B()", label="b")  # type: ignore[arg-type]
        assert len(ctx.route_calls) == 1
        handler = ctx.route_calls[0][1]
        assert len(handler.__closure__[0].cell_contents) == 2  # providers list

    @pytest.mark.asyncio
    async def test_accumulated_providers_delivered_in_order(self) -> None:
        ctx = _StubContext()
        await install_document_script_injection(ctx, lambda: "A()", label="a")  # type: ignore[arg-type]
        await install_document_script_injection(ctx, lambda: "B()", label="b")  # type: ignore[arg-type]
        handler = ctx.route_calls[0][1]
        route, _ = _make_route()
        await handler(route)
        body = route.fulfill.await_args.kwargs["body"]
        assert b"<script>A()</script><script>B()</script>" in body
