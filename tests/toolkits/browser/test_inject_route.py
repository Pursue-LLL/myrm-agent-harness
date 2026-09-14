"""Unit tests for enhancers.inject_route (document-response script injection)."""

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
) -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Build (route, fallback_mock, fulfill_mock) mimicking patchright primitives."""
    if body is None:
        body = b"<html><head><title>base</title></head><body></body></html>"
    route = MagicMock()
    route.request.resource_type = resource_type
    route.fallback = AsyncMock()
    route.fulfill = AsyncMock()
    route.fetch = AsyncMock()
    response = MagicMock()
    response.headers = {"content-type": content_type}
    response.body = AsyncMock(return_value=body)
    route.fetch.return_value = response
    return route, route.fallback, route.fulfill


class TestInjectHandler:
    @pytest.mark.asyncio
    async def test_document_html_gets_script_injected(self) -> None:
        route, fallback, fulfill = _make_route()
        await _inject_handler(route, [lambda: "console.log(1)"])
        route.fetch.assert_awaited_once()
        fallback.assert_not_called()
        kwargs = fulfill.await_args.kwargs
        assert b"<script>console.log(1)</script>" in kwargs["body"]
        assert b"</head>" in kwargs["body"]

    @pytest.mark.asyncio
    async def test_multiple_providers_all_injected_once(self) -> None:
        route, _, fulfill = _make_route()
        await _inject_handler(route, [lambda: "A()", lambda: "B()"])
        body = fulfill.await_args.kwargs["body"]
        assert b"<script>A()</script><script>B()</script>" in body

    @pytest.mark.asyncio
    async def test_script_source_with_closing_tag_is_escaped(self) -> None:
        route, _, fulfill = _make_route()
        await _inject_handler(route, [lambda: 'document.write("</script><b>x</b>")'])
        body = fulfill.await_args.kwargs["body"]
        assert b"<\\/script>" in body
        assert b"</script><b>" not in body.replace(b"<\\/script>", b"")

    @pytest.mark.asyncio
    async def test_non_document_falls_through(self) -> None:
        route, fallback, fulfill = _make_route(resource_type="xhr")
        await _inject_handler(route, [lambda: "A()"])
        route.fetch.assert_not_called()
        fallback.assert_awaited_once()
        fulfill.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_html_falls_through(self) -> None:
        route, fallback, fulfill = _make_route(content_type="application/json")
        await _inject_handler(route, [lambda: "A()"])
        fallback.assert_awaited_once()
        fulfill.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_body_fulfill_without_rewrite(self) -> None:
        route, _, fulfill = _make_route(body=b"")
        await _inject_handler(route, [lambda: "A()"])
        fulfill.assert_awaited_once()
        assert "body" not in fulfill.await_args.kwargs

    @pytest.mark.asyncio
    async def test_no_head_tag_prepends_to_body(self) -> None:
        route, _, fulfill = _make_route(body=b"<html><body>x</body></html>")
        await _inject_handler(route, [lambda: "A()"])
        body = fulfill.await_args.kwargs["body"]
        assert body.startswith(b"<script>A()</script>")

    @pytest.mark.asyncio
    async def test_fetch_error_never_blocks_navigation(self) -> None:
        route, fallback, _ = _make_route()
        route.fetch = AsyncMock(side_effect=RuntimeError("network gone"))
        await _inject_handler(route, [lambda: "A()"])
        fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_utf8_charset_roundtrip(self) -> None:
        """gbk page: injected script stays intact, original bytes preserved."""
        route, _, fulfill = _make_route(
            content_type="text/html; charset=gbk",
            body='<html><head><title>页</title></head><body>中文</body></html>'.encode("gbk"),
        )
        await _inject_handler(route, [lambda: "mark()"])
        kwargs = fulfill.await_args.kwargs
        assert b"<script>mark()</script>" in kwargs["body"].decode("gbk").encode()
        assert kwargs["body"].decode("gbk").endswith("</body></html>")

    @pytest.mark.asyncio
    async def test_undeclared_charset_invalid_bytes_fall_through(self) -> None:
        """Undeclared charset with invalid utf-8 bytes: fulfill untouched."""
        route, fallback, fulfill = _make_route(
            content_type="text/html",
            body=b"<html><head></head><body>\xff\xfe</body></html>",
        )
        await _inject_handler(route, [lambda: "A()"])
        fallback.assert_awaited_once()
        fulfill.assert_not_called()


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
        await install_document_script_injection(ctx, lambda: "A()", label="a")
        assert len(ctx.route_calls) == 1

    @pytest.mark.asyncio
    async def test_second_call_accumulates_provider_without_new_handler(self) -> None:
        ctx = _StubContext()
        await install_document_script_injection(ctx, lambda: "A()", label="a")
        await install_document_script_injection(ctx, lambda: "B()", label="b")
        assert len(ctx.route_calls) == 1
        handler = ctx.route_calls[0][1]
        assert len(handler.__closure__[0].cell_contents) == 2  # providers list

    @pytest.mark.asyncio
    async def test_accumulated_providers_delivered_in_order(self) -> None:
        ctx = _StubContext()
        await install_document_script_injection(ctx, lambda: "A()", label="a")
        await install_document_script_injection(ctx, lambda: "B()", label="b")
        handler = ctx.route_calls[0][1]
        route, _, fulfill = _make_route()
        await handler(route)
        body = fulfill.await_args.kwargs["body"]
        assert b"<script>A()</script><script>B()</script>" in body