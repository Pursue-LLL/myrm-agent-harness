"""Tests for PathValidator — security validation for file paths.

Covers:
- Path traversal detection
- Symlink detection with actionable hints
- Dangerous path blocking
- Path depth limits
- MCP virtual path bypass
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.validators.path_validator import (
    PathValidator,
)


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.operation = MagicMock()
    ctx.operation.value = "create"
    return ctx


class TestPathTraversal:
    @pytest.mark.asyncio
    async def test_rejects_dotdot_traversal(self) -> None:
        validator = PathValidator()
        with pytest.raises(PermissionError, match="Path traversal"):
            await validator._do_validate(_make_context(), "../etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_encoded_traversal(self) -> None:
        validator = PathValidator()
        with pytest.raises(PermissionError, match="Path traversal"):
            await validator._do_validate(_make_context(), "%2e%2e/etc/passwd")


class TestSymlinkDetection:
    @pytest.mark.asyncio
    async def test_parent_symlink_error_contains_hint(self) -> None:
        """Symlink in parent directory error must include actionable hint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            link_dir = os.path.join(tmpdir, "linked")
            target_dir = os.path.join(tmpdir, "target")
            os.makedirs(target_dir)
            os.symlink(target_dir, link_dir)

            validator = PathValidator()
            file_path = os.path.join(link_dir, "test.py")

            with pytest.raises(PermissionError) as exc_info:
                await validator._do_validate(_make_context(), file_path)

            error_msg = str(exc_info.value)
            assert "Hint:" in error_msg
            assert "workspace-relative" in error_msg

    @pytest.mark.asyncio
    async def test_direct_symlink_rejected(self) -> None:
        """Direct symlink target is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "real.txt")
            Path(target).write_text("data")
            link = os.path.join(tmpdir, "link.txt")
            os.symlink(target, link)

            validator = PathValidator()
            with pytest.raises(PermissionError, match="Symbolic links are not allowed"):
                await validator._do_validate(_make_context(), link)

    @pytest.mark.asyncio
    async def test_symlink_allowed_when_follow_symlinks_enabled(self) -> None:
        """When follow_symlinks=True, symlinks should not be rejected."""
        from myrm_agent_harness.agent.config import FileIOConfig

        config = FileIOConfig(follow_symlinks=True)
        validator = PathValidator(io_config=config)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "real.txt")
            Path(target).write_text("data")
            link = os.path.join(tmpdir, "link.txt")
            os.symlink(target, link)

            await validator._do_validate(_make_context(), link)


class TestMcpVirtualPath:
    @pytest.mark.asyncio
    async def test_mcp_path_skips_all_validation(self) -> None:
        validator = PathValidator()
        await validator._do_validate(_make_context(), "/mcp/server/resource")


class TestPathDepth:
    @pytest.mark.asyncio
    async def test_rejects_excessively_deep_path(self) -> None:
        from myrm_agent_harness.agent.config import FileIOConfig

        config = FileIOConfig(max_path_depth=5)
        validator = PathValidator(io_config=config)
        deep_path = "/a/b/c/d/e/f/g/h/i/j"
        with pytest.raises(ValueError, match="Path depth exceeds"):
            await validator._do_validate(_make_context(), deep_path)


class TestAllowedBasePaths:
    @pytest.mark.asyncio
    async def test_rejects_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_dir:
            validator = PathValidator(allowed_base_paths=[allowed_dir])
            with pytest.raises(PermissionError, match="outside allowed"):
                await validator._do_validate(_make_context(), "/usr/bin/ls")

    @pytest.mark.asyncio
    async def test_allows_inside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_dir:
            from myrm_agent_harness.agent.config import FileIOConfig

            config = FileIOConfig(follow_symlinks=True)
            validator = PathValidator(
                allowed_base_paths=[allowed_dir], io_config=config
            )
            valid_path = os.path.join(allowed_dir, "test.txt")
            await validator._do_validate(_make_context(), valid_path)


class TestDangerousPaths:
    @pytest.mark.asyncio
    async def test_rejects_etc_passwd(self) -> None:
        from myrm_agent_harness.agent.config import FileIOConfig

        config = FileIOConfig(follow_symlinks=True)
        validator = PathValidator(io_config=config)
        with pytest.raises(PermissionError, match="dangerous path"):
            await validator._do_validate(_make_context(), "/etc/passwd")
