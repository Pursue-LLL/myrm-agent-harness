# [POS]: myrm_agent_harness/toolkits/memory/sovereign_migration/competitor_adapter.py
# [INPUT]: logging, os, pathlib.Path, shutil, types
# [OUTPUT]: CompetitorIngestionAdapter
"""Universal competitor ingestion and translation adapter (Hermes, Claude Code, Codex).

Probes host environment for third-party agent configurations, memories, and skills,
translating them losslessly into Myrm native wiki memories and agent playbooks.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from myrm_agent_harness.toolkits.memory.sovereign_migration.types import (
    CompetitorDetectResult,
    CompetitorImportResult,
    CompetitorType,
)

logger = logging.getLogger(__name__)


class CompetitorIngestionAdapter:
    """Detects and imports digital assets from competitor setups without loss."""

    def __init__(self) -> None:
        logger.info("CompetitorIngestionAdapter initialized")

    def detect(
        self,
        home_dir: Path | str | None = None,
        workspace_root: Path | str | None = None,
    ) -> CompetitorDetectResult:
        """Probe local workstation environment for competitor directory structures."""
        home = Path(home_dir).resolve() if home_dir else Path.home().resolve()
        ws = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()

        detected: list[CompetitorType] = []
        hermes_path: str | None = None
        claude_rule: str | None = None
        codex_rule: str | None = None

        # 1. Probe Hermes (~/.hermes)
        hermes_candidate = home / ".hermes"
        if hermes_candidate.exists() and hermes_candidate.is_dir():
            detected.append(CompetitorType.HERMES)
            hermes_path = str(hermes_candidate)

        # 2. Probe Claude Code (~/.claude/CLAUDE.md or workspace/CLAUDE.md)
        claude_home_rule = home / ".claude" / "CLAUDE.md"
        claude_ws_rule = ws / "CLAUDE.md"
        if claude_home_rule.exists():
            detected.append(CompetitorType.CLAUDE_CODE)
            claude_rule = str(claude_home_rule)
        elif claude_ws_rule.exists():
            detected.append(CompetitorType.CLAUDE_CODE)
            claude_rule = str(claude_ws_rule)

        # 3. Probe Codex (~/.codex/AGENTS.md or workspace/AGENTS.md)
        codex_home_rule = home / ".codex" / "AGENTS.md"
        codex_ws_rule = ws / "AGENTS.md"
        if codex_home_rule.exists():
            detected.append(CompetitorType.CODEX)
            codex_rule = str(codex_home_rule)
        elif codex_ws_rule.exists():
            detected.append(CompetitorType.CODEX)
            codex_rule = str(codex_ws_rule)

        return CompetitorDetectResult(
            detected_competitors=detected,
            hermes_dir=hermes_path,
            claude_code_rule_path=claude_rule,
            codex_rule_path=codex_rule,
        )

    def ingest(
        self,
        competitor: CompetitorType,
        source_path: Path | str,
        target_destination_dir: Path | str,
    ) -> CompetitorImportResult:
        """Translate competitor data into Myrm standard memory and rule assets."""
        src = Path(source_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source competitor path '{src}' does not exist.")

        target_dir = Path(target_destination_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        imported_rules = 0
        imported_skills = 0
        imported_memories = 0
        details: list[str] = []

        if competitor == CompetitorType.HERMES:
            # Hermes: copies memories/ into wiki_memory_data/, skills/ into skills/
            mem_src = src / "memories"
            if mem_src.exists() and mem_src.is_dir():
                target_mem = target_dir / "wiki_memory_data"
                target_mem.mkdir(parents=True, exist_ok=True)
                for root, _, files in os.walk(mem_src):
                    for f in files:
                        file_p = Path(root) / f
                        shutil.copy2(file_p, target_mem / f)
                        imported_memories += 1
                details.append(f"Ingested {imported_memories} memory files from Hermes")

            skill_src = src / "skills"
            if skill_src.exists() and skill_src.is_dir():
                target_skills = target_dir / "skills"
                target_skills.mkdir(parents=True, exist_ok=True)
                for item in skill_src.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, target_skills / item.name, dirs_exist_ok=True)
                        imported_skills += 1
                    elif item.is_file():
                        shutil.copy2(item, target_skills / item.name)
                        imported_skills += 1
                details.append(f"Ingested {imported_skills} skills from Hermes")

            # Check config.yaml or instructions
            config_file = src / "config.yaml"
            if config_file.exists():
                rules_dir = target_dir / "rules"
                rules_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(config_file, rules_dir / "hermes_config.yaml")
                imported_rules += 1
                details.append("Preserved Hermes config.yaml as rules/hermes_config.yaml")

        elif competitor == CompetitorType.CLAUDE_CODE:
            rules_dir = target_dir / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            rule_dest = rules_dir / "claude_code_rule.md"
            content = src.read_text(encoding="utf-8")
            wrapped_content = f"# Imported from Claude Code Rule ({src.name})\n\n{content}"
            rule_dest.write_text(wrapped_content, encoding="utf-8")
            imported_rules += 1
            details.append(f"Ingested Claude Code instructions into {rule_dest.name}")

        elif competitor == CompetitorType.CODEX:
            rules_dir = target_dir / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            rule_dest = rules_dir / "codex_rule.md"
            content = src.read_text(encoding="utf-8")
            wrapped_content = f"# Imported from Codex Rule ({src.name})\n\n{content}"
            rule_dest.write_text(wrapped_content, encoding="utf-8")
            imported_rules += 1
            details.append(f"Ingested Codex instructions into {rule_dest.name}")

        return CompetitorImportResult(
            success=True,
            imported_rules_count=imported_rules,
            imported_skills_count=imported_skills,
            imported_memories_count=imported_memories,
            details=details,
        )
