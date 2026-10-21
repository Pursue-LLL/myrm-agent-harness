"""Tests for LLM logger hook registration mechanism."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.toolkits.llms.utils.logger import (
    _request_hooks,
    _response_hooks,
    register_request_hook,
    register_response_hook,
)


class TestResponseHooks:
    def setup_method(self) -> None:
        self._original = _response_hooks.copy()
        _response_hooks.clear()

    def teardown_method(self) -> None:
        _response_hooks.clear()
        _response_hooks.extend(self._original)

    def test_register_response_hook(self) -> None:
        hook = MagicMock()
        register_response_hook(hook)
        assert hook in _response_hooks

    def test_idempotent_registration(self) -> None:
        hook = MagicMock()
        register_response_hook(hook)
        register_response_hook(hook)
        assert _response_hooks.count(hook) == 1

    def test_multiple_hooks(self) -> None:
        h1, h2 = MagicMock(), MagicMock()
        register_response_hook(h1)
        register_response_hook(h2)
        assert len(_response_hooks) == 2


class TestRequestHooks:
    def setup_method(self) -> None:
        self._original = _request_hooks.copy()
        _request_hooks.clear()

    def teardown_method(self) -> None:
        _request_hooks.clear()
        _request_hooks.extend(self._original)

    def test_register_request_hook(self) -> None:
        hook = MagicMock()
        register_request_hook(hook)
        assert hook in _request_hooks

    def test_idempotent_registration(self) -> None:
        hook = MagicMock()
        register_request_hook(hook)
        register_request_hook(hook)
        assert _request_hooks.count(hook) == 1
