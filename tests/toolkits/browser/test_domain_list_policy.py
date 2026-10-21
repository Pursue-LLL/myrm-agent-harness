"""Unit tests for the per-context domain lists (``domain_filter.context_lists``) and their request-filter use.

Real-Chromium behavior (redirect targets judged after the load) is proven in
``test_domain_lists_redirect_integration.py``; these tests pin the verdict rule, the registry and
the request filter's decisions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist, install_domain_filter
from myrm_agent_harness.toolkits.browser.domain_filter.context_lists import (
    DomainListPolicy,
    bind_domain_lists,
    domain_lists_for,
)


def _lists(*patterns: str) -> DomainAllowlist:
    return DomainAllowlist.from_strings(patterns)


class TestVerdict:
    def test_blocklist_names_the_blocklist(self) -> None:
        policy = DomainListPolicy(_lists(), _lists("bad.example"))
        assert policy.violation("bad.example") == "blocklist"
        assert policy.violation("good.example") is None

    def test_allowlist_names_the_allowlist(self) -> None:
        policy = DomainListPolicy(_lists("good.example"))
        assert policy.violation("other.example") == "allowlist"
        assert policy.violation("good.example") is None

    def test_blocklist_wins_over_allowlist(self) -> None:
        policy = DomainListPolicy(_lists("*.example"), _lists("bad.example"))
        assert policy.violation("bad.example") == "blocklist"
        assert policy.violation("www.example") is None

    def test_a_host_failing_both_lists_is_reported_as_blocklisted(self) -> None:
        policy = DomainListPolicy(_lists("good.example"), _lists("bad.example"))
        assert policy.violation("bad.example") == "blocklist"

    def test_wildcard_covers_the_bare_domain_and_subdomains_only(self) -> None:
        policy = DomainListPolicy(_lists("*.good.example"))
        assert policy.violation("good.example") is None
        assert policy.violation("a.b.good.example") is None
        assert policy.violation("notgood.example") == "allowlist"

    def test_matching_is_case_and_idn_insensitive(self) -> None:
        policy = DomainListPolicy(_lists("münchen.example"), _lists("BAD.example"))
        assert policy.violation("xn--mnchen-3ya.example") is None
        assert policy.violation("Bad.Example") == "blocklist"

    def test_empty_lists_impose_nothing(self) -> None:
        policy = DomainListPolicy(_lists(), _lists())
        assert policy.is_empty
        assert policy.violation("anything.example") is None
        assert DomainListPolicy(_lists()).is_empty

    def test_a_missing_hostname_fails_closed_under_an_allowlist_only(self) -> None:
        assert DomainListPolicy(_lists("good.example")).violation("") == "allowlist"
        assert DomainListPolicy(_lists(), _lists("bad.example")).violation("") is None

    def test_any_list_makes_the_policy_non_empty(self) -> None:
        assert not DomainListPolicy(_lists("good.example")).is_empty
        assert not DomainListPolicy(_lists(), _lists("bad.example")).is_empty


class _Context:
    """Hashable, weak-referenceable stand-in with the one method the filter installer calls."""

    def __init__(self) -> None:
        self.route = AsyncMock()


class TestRegistry:
    def test_a_context_has_no_policy_until_one_is_bound(self) -> None:
        assert domain_lists_for(_Context()) is None  # type: ignore[arg-type]

    def test_policies_never_leak_between_contexts(self) -> None:
        first, second = _Context(), _Context()
        policy = DomainListPolicy(_lists("good.example"))
        bind_domain_lists(first, policy)  # type: ignore[arg-type]
        assert domain_lists_for(first) is policy  # type: ignore[arg-type]
        assert domain_lists_for(second) is None  # type: ignore[arg-type]


async def _install(context: _Context, allow: tuple[str, ...] = (), block: tuple[str, ...] = ()) -> None:
    await install_domain_filter(
        context,  # type: ignore[arg-type]
        _lists(*allow),
        domain_blocklist=_lists(*block),
        enable_cdp_audit=False,
        allow_private_networks=True,
    )


def _route(url: str, resource_type: str = "xhr") -> MagicMock:
    route = MagicMock()
    route.request.url = url
    route.request.resource_type = resource_type
    route.abort = AsyncMock()
    route.fallback = AsyncMock()
    return route


async def _handler(context: _Context) -> Callable[[MagicMock], Awaitable[None]]:
    return context.route.await_args_list[-1].args[1]


class TestRequestFilterSharesThePolicy:
    @pytest.mark.asyncio
    async def test_installing_lists_binds_the_policy_to_the_context(self) -> None:
        context = _Context()
        await _install(context, allow=("good.example",), block=("bad.example",))
        policy = domain_lists_for(context)  # type: ignore[arg-type]
        assert policy is not None
        assert policy.violation("bad.example") == "blocklist"
        assert policy.violation("other.example") == "allowlist"

    @pytest.mark.asyncio
    async def test_a_filter_without_lists_binds_nothing(self) -> None:
        context = _Context()
        await install_domain_filter(
            context,  # type: ignore[arg-type]
            _lists(),
            resource_block=MagicMock(
                block_images=True,
                block_stylesheets=False,
                block_scripts=False,
                block_fonts=False,
                block_media=False,
                block_ad_domains=False,
            ),
            enable_cdp_audit=False,
            allow_private_networks=True,
        )
        assert domain_lists_for(context) is None  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_requests_are_judged_by_the_bound_policy(self) -> None:
        context = _Context()
        await _install(context, allow=("*.example",), block=("bad.example",))
        handler = await _handler(context)

        blocked, outside, allowed = (
            _route("https://bad.example/x"),
            _route("https://elsewhere.test/x"),
            _route("https://www.example/x"),
        )
        for route in (blocked, outside, allowed):
            await handler(route)
        blocked.abort.assert_awaited_once()
        outside.abort.assert_awaited_once()
        allowed.abort.assert_not_called()
        allowed.fallback.assert_awaited_once()
