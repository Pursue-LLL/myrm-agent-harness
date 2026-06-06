"""Tests for ConfigProtectionValidator — blocks agent modifications to linter configs.

Covers:
- Blocking edits to existing config files
- Allowing first-time creation of config files
- Allowing read/view of config files
- Non-protected files pass through
- All protected filename variants are recognized
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationType,
)
from myrm_agent_harness.agent.meta_tools.file_ops.validators.config_protection_validator import (
    PROTECTED_CONFIG_NAMES,
    ConfigProtectionValidator,
)


def _make_context(operation: OperationType) -> MagicMock:
    ctx = MagicMock()
    ctx.operation = operation
    return ctx


class TestBlockExistingConfigEdits:
    """Agent must not modify existing linter/formatter configs."""

    @pytest.mark.asyncio
    async def test_blocks_str_replace_on_existing_eslintrc(self, tmp_path: object) -> None:
        with tempfile.NamedTemporaryFile(suffix="", prefix=".eslintrc", dir=None, delete=False) as f:
            f.write(b'{"rules": {}}')
            config_path = f.name

        try:
            os.rename(config_path, os.path.join(os.path.dirname(config_path), ".eslintrc.json"))
            config_path = os.path.join(os.path.dirname(config_path), ".eslintrc.json")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="BLOCKED"):
                await validator._do_validate(_make_context(OperationType.STR_REPLACE), config_path)
        finally:
            if os.path.exists(config_path):
                os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_blocks_create_overwrite_on_existing_tsconfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "tsconfig.json")
            with open(config_path, "w") as f:
                f.write('{"compilerOptions": {"strict": true}}')

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="BLOCKED"):
                await validator._do_validate(_make_context(OperationType.CREATE), config_path)

    @pytest.mark.asyncio
    async def test_blocks_prettier_config_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".prettierrc.json")
            with open(config_path, "w") as f:
                f.write("{}")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="BLOCKED"):
                await validator._do_validate(_make_context(OperationType.STR_REPLACE), config_path)

    @pytest.mark.asyncio
    async def test_blocks_biome_config_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "biome.json")
            with open(config_path, "w") as f:
                f.write("{}")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="BLOCKED"):
                await validator._do_validate(_make_context(OperationType.CREATE), config_path)

    @pytest.mark.asyncio
    async def test_blocks_ruff_toml_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "ruff.toml")
            with open(config_path, "w") as f:
                f.write("[lint]\nselect = ['ALL']")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="BLOCKED"):
                await validator._do_validate(_make_context(OperationType.STR_REPLACE), config_path)


class TestAllowFirstTimeCreation:
    """First-time creation of config files must be allowed (project scaffolding)."""

    @pytest.mark.asyncio
    async def test_allows_creating_new_eslintrc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".eslintrc.json")
            # File does NOT exist

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.CREATE), config_path)

    @pytest.mark.asyncio
    async def test_allows_creating_new_tsconfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "tsconfig.json")

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.CREATE), config_path)


class TestViewAlwaysAllowed:
    """Reading/viewing config files must never be blocked."""

    @pytest.mark.asyncio
    async def test_allows_view_of_existing_eslintrc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".eslintrc.json")
            with open(config_path, "w") as f:
                f.write("{}")

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.VIEW), config_path)


class TestNonProtectedFilesPassThrough:
    """Normal source files must never be blocked."""

    @pytest.mark.asyncio
    async def test_allows_editing_python_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = os.path.join(tmpdir, "main.py")
            with open(src_path, "w") as f:
                f.write("print('hello')")

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.STR_REPLACE), src_path)

    @pytest.mark.asyncio
    async def test_allows_editing_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_path = os.path.join(tmpdir, "package.json")
            with open(pkg_path, "w") as f:
                f.write('{"name": "test"}')

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.STR_REPLACE), pkg_path)

    @pytest.mark.asyncio
    async def test_allows_editing_pyproject_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = os.path.join(tmpdir, "pyproject.toml")
            with open(toml_path, "w") as f:
                f.write("[project]\nname = 'test'")

            validator = ConfigProtectionValidator()
            await validator._do_validate(_make_context(OperationType.STR_REPLACE), toml_path)


class TestProtectedNamesCompleteness:
    """Verify the protected set covers expected configs."""

    def test_eslint_variants_covered(self) -> None:
        eslint_names = [n for n in PROTECTED_CONFIG_NAMES if "eslint" in n]
        assert len(eslint_names) >= 11

    def test_prettier_variants_covered(self) -> None:
        prettier_names = [n for n in PROTECTED_CONFIG_NAMES if "prettier" in n.lower()]
        assert len(prettier_names) >= 9

    def test_biome_covered(self) -> None:
        assert "biome.json" in PROTECTED_CONFIG_NAMES
        assert "biome.jsonc" in PROTECTED_CONFIG_NAMES

    def test_ruff_covered(self) -> None:
        assert "ruff.toml" in PROTECTED_CONFIG_NAMES
        assert ".ruff.toml" in PROTECTED_CONFIG_NAMES

    def test_pyproject_not_in_protected(self) -> None:
        assert "pyproject.toml" not in PROTECTED_CONFIG_NAMES

    def test_package_json_not_in_protected(self) -> None:
        assert "package.json" not in PROTECTED_CONFIG_NAMES


class TestErrorMessageQuality:
    """Error messages must guide the agent toward the correct behavior."""

    @pytest.mark.asyncio
    async def test_error_mentions_fix_source_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".eslintrc.json")
            with open(config_path, "w") as f:
                f.write("{}")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="Fix the source code"):
                await validator._do_validate(_make_context(OperationType.STR_REPLACE), config_path)

    @pytest.mark.asyncio
    async def test_error_mentions_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "biome.json")
            with open(config_path, "w") as f:
                f.write("{}")

            validator = ConfigProtectionValidator()
            with pytest.raises(PermissionError, match="biome.json"):
                await validator._do_validate(_make_context(OperationType.STR_REPLACE), config_path)
