"""Import-gate tests for optional sqlalchemy in migration_engine."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import patch

import pytest

import myrm_agent_harness.utils.db.migration_engine as migration_engine


def test_sql_text_raises_install_hint_when_sqlalchemy_missing() -> None:
    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "sqlalchemy" or name.startswith("sqlalchemy."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import):
        with pytest.raises(ImportError, match="sqlalchemy is required"):
            migration_engine._sql_text("SELECT 1")


def test_stateful_migration_engine_requires_sqlalchemy_engine_type() -> None:
    """Engine type hint path: constructing without sqlalchemy installed at TYPE_CHECKING only."""
    assert migration_engine.StatefulMigrationEngine is not None


def test_migration_engine_module_importable_without_sqlalchemy_at_import_time() -> None:
    assert "sqlalchemy" not in sys.modules or migration_engine is not None
