"""Unit tests for agent-facing sovereign migration tool and MemoryManager mixin.

[INPUT]
- toolkits.memory.sovereign_migration.tool::create_sovereign_migration_tool, SovereignAssetActionInput
- toolkits.memory.sovereign_migration.types::CompetitorType
- toolkits.memory._manager.sovereign_migration::MemoryManagerSovereignMigrationMixin
- toolkits.memory.manager::MemoryManager

[OUTPUT]
- test_sovereign_tool_detect: tests competitor environment detection action
- test_sovereign_tool_rejects_removed_bundle_actions: tests export/restore are no longer exposed
- test_sovereign_tool_ingest_hermes_into_memories: tests Hermes memories ingested into memories/ directory
- test_memory_manager_sovereign_migration_mixin: tests MemoryManager mixin delegation methods

[POS]
Integration and unit tests ensuring Agent runtime and MemoryManager can detect and ingest competitor assets.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory._manager.sovereign_migration import (
    MemoryManagerSovereignMigrationMixin,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.sovereign_migration.tool import (
    create_sovereign_migration_tool,
)
from myrm_agent_harness.toolkits.memory.sovereign_migration.types import CompetitorType


class DummySovereignMemoryManager(MemoryManagerSovereignMigrationMixin):
    """Dummy manager subclass for testing sovereign migration mixin."""

    def __init__(self) -> None:
        self.user_id = "test_sovereign_user"


@pytest.fixture
def mock_hermes_dir() -> Path:
    """Create a temporary Hermes data directory."""
    with tempfile.TemporaryDirectory() as td:
        hermes_path = Path(td)
        # Create memories/
        mem_dir = hermes_path / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "user_preferences.md").write_text("# User Preferences\nPrefers async Python.\n", encoding="utf-8")

        # Create skills/
        skills_dir = hermes_path / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "deploy.py").write_text("print('Deploying')\n", encoding="utf-8")

        # Create config.yaml
        (hermes_path / "config.yaml").write_text("model: gpt-4o\n", encoding="utf-8")
        yield hermes_path


def test_sovereign_tool_detect() -> None:
    """Ensure agent tool returns structured JSON of detected competitor environments."""
    tool = create_sovereign_migration_tool()
    raw = tool.invoke({"action": "detect"})
    data = json.loads(raw)

    assert data["action"] == "detect"
    assert "result" in data
    assert "detected_competitors" in data["result"]


def test_sovereign_tool_rejects_removed_bundle_actions() -> None:
    """Whole-instance export/restore moved to infra.state_archive; the tool must not offer it."""
    tool = create_sovereign_migration_tool()
    for action in ("export", "restore"):
        data = json.loads(tool.invoke({"action": action}))
        assert data == {"error": f"Unknown action '{action}'"}


def test_sovereign_tool_ingest_hermes_into_memories(mock_hermes_dir: Path) -> None:
    """Ensure agent tool ingests Hermes memories directly into memories/ directory."""
    with tempfile.TemporaryDirectory() as td_dest:
        dest = Path(td_dest)
        tool = create_sovereign_migration_tool()

        raw = tool.invoke(
            {
                "action": "ingest",
                "source_dir": str(mock_hermes_dir),
                "target_destination_dir": str(dest),
                "competitor_type": "hermes",
            }
        )
        data = json.loads(raw)

        assert data["action"] == "ingest"
        assert data["success"] is True
        assert data["imported_memories_count"] == 1
        assert data["imported_skills_count"] == 1
        assert data["imported_rules_count"] == 1

        # Check target files
        target_memories = dest / "memories"
        assert target_memories.exists()
        assert (target_memories / "user_preferences.md").exists()
        assert not (dest / "wiki_memory_data").exists()


def test_memory_manager_sovereign_migration_mixin(mock_hermes_dir: Path) -> None:
    """Verify MemoryManager integrates sovereign migration methods."""
    assert issubclass(MemoryManager, MemoryManagerSovereignMigrationMixin)

    manager = DummySovereignMemoryManager()

    with tempfile.TemporaryDirectory() as td_dst:
        dst = Path(td_dst)

        detected = manager.detect_competitors()
        assert isinstance(detected.detected_competitors, list)

        ingest_res = manager.ingest_competitor_assets(
            competitor=CompetitorType.HERMES,
            source_path=mock_hermes_dir,
            target_destination_dir=dst,
        )
        assert ingest_res.success is True
        assert ingest_res.imported_memories_count == 1
        assert (dst / "memories" / "user_preferences.md").exists()
