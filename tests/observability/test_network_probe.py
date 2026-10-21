"""Tests for the staggered first-win network probe.

Covers:
- a blocked/slow first URL must not hide a reachable fallback
- a healthy network issues a single request
- when every URL is slow the probe reports within its own budget and leaves no tasks behind
- the budget invariant that keeps the verdict inside the manager's per-hook limit
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Self

import pytest

from myrm_agent_harness.observability.diagnostics import probes
from myrm_agent_harness.observability.diagnostics.manager import DIAGNOSTIC_HOOK_TIMEOUT_S

_PRIMARY, _SECOND, _THIRD = probes._NETWORK_PROBE_URLS

Behavior = Callable[[], Awaitable[SimpleNamespace]]


async def _ok() -> SimpleNamespace:
    return SimpleNamespace(status_code=204)


async def _server_error() -> SimpleNamespace:
    return SimpleNamespace(status_code=503)


async def _hang() -> SimpleNamespace:
    await asyncio.sleep(60)
    return SimpleNamespace(status_code=204)


async def _refuse() -> SimpleNamespace:
    raise ConnectionError("blocked")


class _FakeClient:
    def __init__(self, behaviors: dict[str, Behavior]) -> None:
        self._behaviors = behaviors
        self.calls: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get(self, url: str, **_kwargs: object) -> SimpleNamespace:
        self.calls.append(url)
        return await self._behaviors[url]()


@pytest.fixture
def fast_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "_NETWORK_PROBE_STAGGER_S", 0.05)
    monkeypatch.setattr(probes, "_NETWORK_PROBE_BUDGET_S", 0.4)


def _install(monkeypatch: pytest.MonkeyPatch, behaviors: dict[str, Behavior]) -> _FakeClient:
    client = _FakeClient(behaviors)
    monkeypatch.setattr("myrm_agent_harness.infra.tls_compat.create_httpx_client", lambda **_kwargs: client)
    return client


@pytest.mark.usefixtures("fast_timing")
async def test_blocked_first_url_does_not_hide_reachable_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, {_PRIMARY: _hang, _SECOND: _ok, _THIRD: _ok})

    started = time.monotonic()
    report = await probes.check_network_health()

    assert report.status == "pass"
    assert _SECOND in report.detail
    assert time.monotonic() - started < probes._NETWORK_PROBE_BUDGET_S
    assert client.calls == [_PRIMARY, _SECOND]


@pytest.mark.usefixtures("fast_timing")
async def test_failing_first_url_falls_through_without_waiting_for_stagger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "_NETWORK_PROBE_STAGGER_S", 30.0)
    _install(monkeypatch, {_PRIMARY: _refuse, _SECOND: _server_error, _THIRD: _ok})

    started = time.monotonic()
    report = await probes.check_network_health()

    assert report.status == "pass"
    assert _THIRD in report.detail
    assert time.monotonic() - started < 1.0


@pytest.mark.usefixtures("fast_timing")
async def test_healthy_network_issues_a_single_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, {_PRIMARY: _ok, _SECOND: _ok, _THIRD: _ok})

    report = await probes.check_network_health()

    assert report.status == "pass"
    assert client.calls == [_PRIMARY]


@pytest.mark.usefixtures("fast_timing")
async def test_every_url_failing_reports_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {_PRIMARY: _refuse, _SECOND: _server_error, _THIRD: _refuse})

    report = await probes.check_network_health()

    assert report.status == "fail"
    assert "Internet is not available" in report.message
    assert "ConnectionError: blocked" in report.detail
    assert "HTTP 503" in report.detail


@pytest.mark.usefixtures("fast_timing")
async def test_all_slow_reports_within_budget_and_leaves_no_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, {_PRIMARY: _hang, _SECOND: _hang, _THIRD: _hang})

    started = time.monotonic()
    report = await probes.check_network_health()
    elapsed = time.monotonic() - started

    assert report.status == "fail"
    assert "within" in report.detail
    assert elapsed < probes._NETWORK_PROBE_BUDGET_S + 0.3
    assert client.calls == [_PRIMARY, _SECOND, _THIRD]
    assert asyncio.all_tasks() == {asyncio.current_task()}


def test_probe_budget_stays_below_manager_hook_limit() -> None:
    assert probes._NETWORK_PROBE_BUDGET_S < DIAGNOSTIC_HOOK_TIMEOUT_S
    assert probes._NETWORK_PROBE_REQUEST_TIMEOUT_S <= probes._NETWORK_PROBE_BUDGET_S
