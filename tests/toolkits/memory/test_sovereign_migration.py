# [POS]: tests/toolkits/memory/test_sovereign_migration.py
# [INPUT]: pathlib.Path, tempfile, myrm_agent_harness.toolkits.memory.sovereign_migration
# [OUTPUT]: test_competitor_ingestion_adapter
"""Unit test suite for competitor asset detection and ingestion.

Validates the Hermes, Claude Code and Codex ingestion adapters.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.sovereign_migration import (
    CompetitorIngestionAdapter,
    CompetitorType,
)


def test_competitor_ingestion_adapter() -> None:
    """Verify CompetitorIngestionAdapter detects and translates Hermes, Claude Code, and Codex assets."""
    with (
        tempfile.TemporaryDirectory() as td_home,
        tempfile.TemporaryDirectory() as td_ws,
        tempfile.TemporaryDirectory() as td_target,
    ):
        home_path = Path(td_home).resolve()
        ws_path = Path(td_ws).resolve()
        target_path = Path(td_target).resolve()

        # 1. Setup mock Hermes directory
        hermes_dir = home_path / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        (hermes_dir / "config.yaml").write_text("model: gpt-4o\ntemperature: 0.2\n", encoding="utf-8")
        hermes_mem = hermes_dir / "memories"
        hermes_mem.mkdir(parents=True, exist_ok=True)
        (hermes_mem / "user_pref.md").write_text("User likes concise responses", encoding="utf-8")

        # 2. Setup mock Claude Code rule
        claude_rule = ws_path / "CLAUDE.md"
        claude_rule.write_text("Always write python unit tests using pytest.", encoding="utf-8")

        # 3. Setup mock Codex rule
        codex_rule = ws_path / "AGENTS.md"
        codex_rule.write_text("Follow architecture rules defined in repository.", encoding="utf-8")

        adapter = CompetitorIngestionAdapter()
        detect_res = adapter.detect(home_dir=home_path, workspace_root=ws_path)

        assert CompetitorType.HERMES in detect_res.detected_competitors
        assert CompetitorType.CLAUDE_CODE in detect_res.detected_competitors
        assert CompetitorType.CODEX in detect_res.detected_competitors
        assert detect_res.hermes_dir == str(hermes_dir)

        # 4. Ingest Hermes
        res_hermes = adapter.ingest(
            competitor=CompetitorType.HERMES,
            source_path=hermes_dir,
            target_destination_dir=target_path,
        )
        assert res_hermes.success is True
        assert res_hermes.imported_memories_count == 1
        assert (target_path / "memories" / "user_pref.md").exists()
        assert (target_path / "rules" / "hermes_config.yaml").exists()

        # 5. Ingest Claude Code
        res_claude = adapter.ingest(
            competitor=CompetitorType.CLAUDE_CODE,
            source_path=claude_rule,
            target_destination_dir=target_path,
        )
        assert res_claude.success is True
        assert (target_path / "rules" / "claude_code_rule.md").exists()

        # 6. Ingest Codex
        res_codex = adapter.ingest(
            competitor=CompetitorType.CODEX,
            source_path=codex_rule,
            target_destination_dir=target_path,
        )
        assert res_codex.success is True
        assert (target_path / "rules" / "codex_rule.md").exists()
