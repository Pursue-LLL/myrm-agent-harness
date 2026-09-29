"""Tests for InvariantValidator — pre-write Goal protection.

The patterns exercised here are the ones the UI suggests, which is where the
historical matcher failed: a bare filename such as ``.env`` never matched a
nested or absolute write target, so protection silently did nothing.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
)
from myrm_agent_harness.agent.meta_tools.file_ops.validators.invariant_validator import (
    InvariantValidator,
)
from myrm_agent_harness.agent.middlewares._session_context import set_protected_paths


@pytest.fixture(autouse=True)
def _clear_protected_paths():
    set_protected_paths(())
    yield
    set_protected_paths(())


def _write_target(path: str) -> OperationContext:
    return OperationContext(operation=OperationType.CREATE, executor=None, path=path)


async def _assert_write_allowed(path: str) -> None:
    await InvariantValidator().validate(_write_target(path), path)


async def _assert_write_blocked(path: str) -> None:
    with pytest.raises(PermissionError):
        await InvariantValidator().validate(_write_target(path), path)


class TestNoProtection:
    async def test_empty_patterns_allow_everything(self):
        set_protected_paths(())
        await _assert_write_allowed("app/config/.env")

    async def test_view_operations_are_never_blocked(self):
        set_protected_paths((".env",))
        context = OperationContext(operation=OperationType.VIEW, executor=None, path=".env")
        await InvariantValidator().validate(context, ".env")


class TestDepthIndependentPatterns:
    """A bare filename the user typed must protect that file at any depth."""

    @pytest.mark.parametrize(
        "path",
        [".env", "app/.env", "app/config/.env", "/srv/app/config/.env"],
    )
    async def test_bare_dotenv_is_blocked_at_every_depth(self, path: str):
        set_protected_paths((".env",))
        await _assert_write_blocked(path)

    async def test_directory_pattern_is_blocked(self):
        set_protected_paths(("data/*.csv",))
        await _assert_write_blocked("app/data/x.csv")
        await _assert_write_blocked("/abs/app/data/x.csv")

    async def test_unrelated_path_still_allowed(self):
        set_protected_paths(("data/*.csv",))
        await _assert_write_allowed("app/src/main.py")

    async def test_wildcard_extension_is_blocked(self):
        set_protected_paths(("*.env",))
        await _assert_write_blocked("app/config/.env")
        await _assert_write_blocked(".env")


class TestRecursivePatterns:
    async def test_recursive_directory_pattern(self):
        set_protected_paths(("**/migrations/**",))
        await _assert_write_blocked("migrations/001.sql")
        await _assert_write_blocked("app/db/migrations/001.sql")
        await _assert_write_allowed("app/db/models.py")

    async def test_root_level_recursive_pattern(self):
        set_protected_paths(("**/AGENTS.md",))
        await _assert_write_blocked("AGENTS.md")
        await _assert_write_blocked("packages/app/AGENTS.md")


class TestErrorMessage:
    async def test_error_names_the_matched_pattern(self):
        set_protected_paths(("data/*.csv", "*.env"))
        with pytest.raises(PermissionError) as exc:
            await InvariantValidator().validate(_write_target("a/b/.env"), "a/b/.env")
        message = str(exc.value)
        assert "*.env" in message
        assert "a/b/.env" in message
