"""Tests for SensitiveFileValidator — the write-blocking layer for secrets.

The validator resolves ``SENSITIVE_FILE_PATTERNS`` through the shared matcher,
so its verdict must equal ``path_security.is_sensitive_file()`` for the same
path. These tests pin that equivalence, including for rule shapes that carry no
leading ``**/`` — the case where a matcher duplicated inside this module would
silently disagree with the shared one.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationContext,
    OperationType,
)
from myrm_agent_harness.agent.meta_tools.file_ops.validators import sensitive_file_validator as module
from myrm_agent_harness.agent.meta_tools.file_ops.validators.sensitive_file_validator import (
    SensitiveFileValidator,
)
from myrm_agent_harness.core.security.path import is_sensitive_file
from myrm_agent_harness.core.security.path.pattern import first_matching_pattern

SENSITIVE_PATHS = [
    "id_rsa",
    "a/id_rsa",
    "key.pem",
    "a/b/key.pem",
    ".env",
    "app/config/.env",
    ".env.local",
    "secrets.json",
    "deep/nested/secrets.json",
    "password.txt",
    "a/.aws/credentials",
    "a/.git/config",
]

HARMLESS_PATHS = [
    "README.md",
    "main.py",
    "src/utils.py",
    "package.json",
    "docs/agents_guide.html",
    "src/app/config.ts",
]


def _context(operation: OperationType) -> OperationContext:
    return OperationContext(operation=operation, executor=None, path="x")


async def _verdict(path: str, operation: OperationType = OperationType.CREATE) -> str:
    """Return 'blocked' or 'allowed' for *path* under the real rule set."""
    validator = SensitiveFileValidator()
    try:
        await validator.validate(_context(operation), path)
    except PermissionError:
        return "blocked"
    return "allowed"


class TestSensitiveDetection:
    @pytest.mark.parametrize("path", SENSITIVE_PATHS)
    async def test_sensitive_paths_are_blocked_on_write(self, path: str):
        assert await _verdict(path) == "blocked"

    @pytest.mark.parametrize("path", HARMLESS_PATHS)
    async def test_harmless_paths_are_allowed(self, path: str):
        assert await _verdict(path) == "allowed"

    async def test_mcp_virtual_paths_skip_validation(self):
        assert await _verdict("/mcp/some/package/key.pem") == "allowed"

    async def test_read_is_warn_only_by_default(self):
        assert await _verdict("app/config/.env", OperationType.VIEW) == "allowed"

    async def test_read_can_be_blocked_when_configured(self):
        validator = SensitiveFileValidator(block_sensitive_reads=True)
        with pytest.raises(PermissionError):
            await validator.validate(_context(OperationType.VIEW), "app/config/.env")


class TestSharedMatcherEquivalence:
    """The validator must not hold a second, drifting copy of the rules."""

    @pytest.mark.parametrize("path", SENSITIVE_PATHS + HARMLESS_PATHS)
    async def test_agrees_with_path_security_helper(self, path: str):
        assert await _verdict(path) == ("blocked" if is_sensitive_file(path) else "allowed")

    @pytest.mark.parametrize(
        "path",
        [
            "app/config/prod.yaml",
            "a/b/config/prod.yaml",
            "/abs/app/config/x.yaml",
            "key.pem",
            "a/b/key.pem",
            "README.md",
            "src/main.py",
        ],
    )
    async def test_agrees_for_rules_without_recursive_prefix(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ):
        """A rule written as ``config/*.yaml`` must protect nested matches.

        A matcher anchoring such a rule to the full path would skip
        ``deep/nested/config/prod.yaml`` and leave it unprotected.
        """
        monkeypatch.setattr(
            module, "SENSITIVE_FILE_PATTERNS", ("config/*.yaml", "**/key.pem")
        )
        expected = "blocked" if first_matching_pattern(path, module.SENSITIVE_FILE_PATTERNS) else "allowed"
        assert await _verdict(path) == expected

    @pytest.mark.parametrize(
        "path",
        ["app/config/prod.yaml", "a/b/config/prod.yaml", "/abs/app/config/x.yaml"],
    )
    async def test_nested_config_rule_is_actually_enforced(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(module, "SENSITIVE_FILE_PATTERNS", ("config/*.yaml",))
        assert await _verdict(path) == "blocked"
