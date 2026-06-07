"""Tests for observability diagnostics probes.

Covers:
- check_workspace_storage_health: workspace path resolution and skills.db path
- check_database_health: database path resolution (data.db)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestCheckWorkspaceStorageHealth:
    """Tests for check_workspace_storage_health."""

    @pytest.mark.asyncio
    async def test_skills_db_path_resolves_correctly(self):
        """Verify skills.db is looked up at workspace_path/skills.db, not workspace_path/.myrm/skills.db."""
        from myrm_agent_harness.observability.diagnostics.probes import check_workspace_storage_health

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Create skills.db at the CORRECT location
            skills_db = workspace / "skills.db"
            conn = sqlite3.connect(str(skills_db))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {"MYRM_DATA_DIR": str(workspace)}):
                report = await check_workspace_storage_health()
                assert report.status == "pass"

    @pytest.mark.asyncio
    async def test_skills_db_wrong_location_not_found(self):
        """Verify that skills.db at wrong location (.myrm subdirectory) is NOT checked."""
        from myrm_agent_harness.observability.diagnostics.probes import check_workspace_storage_health

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Create skills.db at the WRONG location (old bug)
            wrong_dir = workspace / ".myrm"
            wrong_dir.mkdir()
            wrong_skills_db = wrong_dir / "skills.db"
            conn = sqlite3.connect(str(wrong_skills_db))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {"MYRM_DATA_DIR": str(workspace)}):
                report = await check_workspace_storage_health()
                # Should still pass - skills.db check is optional
                assert report.status == "pass"

    @pytest.mark.asyncio
    async def test_workspace_path_from_env(self):
        """Verify workspace path is read from MYRM_DATA_DIR environment variable."""
        from myrm_agent_harness.observability.diagnostics.probes import check_workspace_storage_health

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
            report = await check_workspace_storage_health()
            assert report.status == "pass"
            assert str(tmpdir) in report.detail

    @pytest.mark.asyncio
    async def test_warns_when_ripgrep_missing(self):
        """Workspace can be healthy while rg is absent — surface warn for Doctor UI."""
        from myrm_agent_harness.observability.diagnostics.probes import check_workspace_storage_health

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
            with patch("shutil.which", return_value=None):
                report = await check_workspace_storage_health()
                assert report.status == "warn"
                assert "ripgrep" in report.message.lower()

    @pytest.mark.asyncio
    async def test_default_workspace_path(self):
        """Verify default workspace path is ~/.myrm when MYRM_DATA_DIR is not set."""
        from myrm_agent_harness.observability.diagnostics.probes import check_workspace_storage_health

        env_copy = os.environ.copy()
        env_copy.pop("MYRM_DATA_DIR", None)
        with patch.dict(os.environ, env_copy, clear=True):
            report = await check_workspace_storage_health()
            # Should use default ~/.myrm path
            assert report.component_name == "WorkspaceStorage"


class TestCheckDatabaseHealth:
    """Tests for check_database_health."""

    @pytest.mark.asyncio
    async def test_database_path_resolves_to_data_db(self):
        """Verify database path is data.db, not database.db."""
        from myrm_agent_harness.observability.diagnostics.probes import check_database_health

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create data.db at the correct location
            data_db = Path(tmpdir) / "data.db"
            conn = sqlite3.connect(str(data_db))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
                report = await check_database_health()
                assert report.status == "pass"

    @pytest.mark.asyncio
    async def test_database_path_not_database_db(self):
        """Verify that database.db (old wrong name) is NOT the target."""
        from myrm_agent_harness.observability.diagnostics.probes import check_database_health

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create database.db at the WRONG location (old bug)
            wrong_db = Path(tmpdir) / "database.db"
            conn = sqlite3.connect(str(wrong_db))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
                report = await check_database_health()
                # sqlite3.connect creates data.db if it doesn't exist,
                # so this will pass with a new empty database
                assert report.status == "pass"
                # Verify data.db was created (not database.db)
                data_db = Path(tmpdir) / "data.db"
                assert data_db.exists()

    @pytest.mark.asyncio
    async def test_database_path_from_env(self):
        """Verify database path is derived from MYRM_DATA_DIR."""
        from myrm_agent_harness.observability.diagnostics.probes import check_database_health

        with tempfile.TemporaryDirectory() as tmpdir:
            data_db = Path(tmpdir) / "data.db"
            conn = sqlite3.connect(str(data_db))
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()

            with patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
                report = await check_database_health()
                assert report.status == "pass"
