# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/targets.py
# [INPUT] models.py (ExternalAgentType, SkillInstallConfig), abc, pathlib.Path
# [OUTPUT] BaseExternalAgentTarget, CursorBridgeTarget, ClaudeCodeBridgeTarget, CodexBridgeTarget, HermesBridgeTarget, OpenClawBridgeTarget

"""Target definitions and template generators for external agent memory bridges.

Defines target-specific installation paths and memory integration directives for
Cursor, Claude Code, Codex, Hermes, and OpenClaw.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from myrm_agent_harness.toolkits.memory.external_bridge.models import (
    ExternalAgentType,
    SkillInstallConfig,
)


class BaseExternalAgentTarget(ABC):
    """Abstract base class for external agent bridge target specifications."""

    @property
    @abstractmethod
    def agent_type(self) -> ExternalAgentType:
        """Type identifier for the external agent."""
        ...

    @abstractmethod
    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        """Resolve default instruction file path for this target agent."""
        ...

    @abstractmethod
    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        """Generate markdown instruction block tailored for this agent."""
        ...

    def _render_common_api_instructions(self, config: SkillInstallConfig) -> str:
        """Render concise instructions for querying and contributing memory."""
        base_url = config.api_base_url.rstrip("/")
        read_only_note = (
            "<!-- Memory bridge is configured in READ-ONLY mode. Do not write. -->\n"
            if config.read_only
            else ""
        )
        contribute_section = (
            f"""
### 2. Save New Insight or Preference
When the user shares persistent preferences, architecture decisions, or key facts:
```bash
curl -s -X POST "{base_url}/api/memory/external/contribute" \\
  -H "Content-Type: application/json" \\
  -d '{{"text": "Extracted key fact or preference", "category": "preference", "confidence": 0.95}}'
```
"""
            if not config.read_only
            else ""
        )

        return f"""## Myrm Unified Memory Bridge
{read_only_note}This workspace is connected to Myrm High-Performance Memory Central.
Use the following endpoints via terminal or tool execution to recall and store memory across agent sessions:

### 1. Recall Relevant Memories
Before designing or writing code, retrieve relevant user preferences and architecture context:
```bash
curl -s -X POST "{base_url}/api/memory/external/query" \\
  -H "Content-Type: application/json" \\
  -d '{{"query": "CURRENT_TASK_TOPIC", "limit": {config.max_recalled_facts}}}'
```
{contribute_section}
Always prioritize recalled user preferences over default assumptions.
"""


class CursorBridgeTarget(BaseExternalAgentTarget):
    """Bridge target for Cursor (.cursorrules or .cursor/rules/myrm-memory.mdc)."""

    @property
    def agent_type(self) -> ExternalAgentType:
        return ExternalAgentType.CURSOR

    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        if global_config:
            return Path.home() / ".cursor" / "rules" / "myrm-memory.mdc"
        root = workspace_root or Path.cwd()
        rules_dir = root / ".cursor" / "rules"
        if rules_dir.exists() and rules_dir.is_dir():
            return rules_dir / "myrm-memory.mdc"
        return root / ".cursorrules"

    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        instructions = self._render_common_api_instructions(config)
        return f"# Cursor Memory Bridge\n\n{instructions}"


class ClaudeCodeBridgeTarget(BaseExternalAgentTarget):
    """Bridge target for Anthropic Claude Code (CLAUDE.md)."""

    @property
    def agent_type(self) -> ExternalAgentType:
        return ExternalAgentType.CLAUDE_CODE

    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        if global_config:
            return Path.home() / ".claude" / "CLAUDE.md"
        root = workspace_root or Path.cwd()
        return root / "CLAUDE.md"

    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        instructions = self._render_common_api_instructions(config)
        return f"# Claude Code Memory Bridge\n\n{instructions}"


class CodexBridgeTarget(BaseExternalAgentTarget):
    """Bridge target for Codex CLI / Environment (CODEX.md)."""

    @property
    def agent_type(self) -> ExternalAgentType:
        return ExternalAgentType.CODEX

    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        if global_config:
            return Path.home() / ".codex" / "instructions.md"
        root = workspace_root or Path.cwd()
        return root / "CODEX.md"

    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        instructions = self._render_common_api_instructions(config)
        return f"# Codex Memory Bridge\n\n{instructions}"


class HermesBridgeTarget(BaseExternalAgentTarget):
    """Bridge target for Hermes Agent (HERMES.md)."""

    @property
    def agent_type(self) -> ExternalAgentType:
        return ExternalAgentType.HERMES

    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        if global_config:
            return Path.home() / ".hermes" / "instructions.md"
        root = workspace_root or Path.cwd()
        return root / "HERMES.md"

    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        instructions = self._render_common_api_instructions(config)
        return f"# Hermes Memory Bridge\n\n{instructions}"


class OpenClawBridgeTarget(BaseExternalAgentTarget):
    """Bridge target for OpenClaw Autonomous System (OPENCLAW.md)."""

    @property
    def agent_type(self) -> ExternalAgentType:
        return ExternalAgentType.OPENCLAW

    def get_default_target_path(
        self, workspace_root: Path | None, global_config: bool = False
    ) -> Path:
        if global_config:
            return Path.home() / ".openclaw" / "rules.md"
        root = workspace_root or Path.cwd()
        return root / "OPENCLAW.md"

    def generate_bridge_content(self, config: SkillInstallConfig) -> str:
        instructions = self._render_common_api_instructions(config)
        return f"# OpenClaw Memory Bridge\n\n{instructions}"
