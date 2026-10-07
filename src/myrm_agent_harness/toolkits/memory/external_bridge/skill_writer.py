# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/skill_writer.py
# [INPUT] models.py, targets.py, registry.py, conflict_detector.py, pathlib.Path
# [OUTPUT] ExternalAgentSkillWriter

"""Safe skill installer and uninstaller with marker isolation for external agents.

Ensures zero damage to pre-existing user configurations by encapsulating all
generated memory instructions inside explicit safe delimiter markers.
"""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.toolkits.memory.external_bridge.conflict_detector import (
    MemoryPluginConflictDetector,
)
from myrm_agent_harness.toolkits.memory.external_bridge.models import (
    SkillBridgeAction,
    SkillInstallConfig,
    SkillInstallResult,
    SkillUninstallResult,
)
from myrm_agent_harness.toolkits.memory.external_bridge.registry import (
    ExternalAgentTargetRegistry,
)

START_MARKER = "<!-- MYRM_MEMORY_BRIDGE_START -->"
END_MARKER = "<!-- MYRM_MEMORY_BRIDGE_END -->"


class ExternalAgentSkillWriter:
    """Installs and uninstalls memory bridge skills with zero configuration destruction."""

    def __init__(self, registry: ExternalAgentTargetRegistry | None = None) -> None:
        self._registry = registry or ExternalAgentTargetRegistry()

    def _wrap_with_markers(self, raw_content: str) -> str:
        """Wrap instructions within explicit safe delimiters."""
        trimmed = raw_content.strip()
        return f"{START_MARKER}\n{trimmed}\n{END_MARKER}\n"

    def _resolve_target_path(self, config: SkillInstallConfig) -> Path:
        """Determine target configuration file path."""
        if config.custom_target_path:
            return config.custom_target_path
        target_adapter = self._registry.get(config.agent_type)
        return target_adapter.get_default_target_path(
            workspace_root=config.workspace_root,
            global_config=config.global_config,
        )

    def install(self, config: SkillInstallConfig) -> SkillInstallResult:
        """Install or update memory bridge instructions in target configuration file."""
        target_path = self._resolve_target_path(config)
        target_adapter = self._registry.get(config.agent_type)
        bridge_content = target_adapter.generate_bridge_content(config)
        marked_block = self._wrap_with_markers(bridge_content)

        conflict_report = MemoryPluginConflictDetector.inspect_file(target_path)
        conflict_msg = (
            f" [Warning: Conflicts detected in {', '.join(conflict_report.conflicting_rules)}]"
            if conflict_report.has_conflict
            else ""
        )

        try:
            if not target_path.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(marked_block, encoding="utf-8")
                return SkillInstallResult(
                    agent_type=config.agent_type,
                    target_path=target_path,
                    action=SkillBridgeAction.CREATED,
                    marker_present=True,
                    success=True,
                    details=f"Created new bridge configuration at {target_path}{conflict_msg}",
                )

            existing_text = target_path.read_text(encoding="utf-8", errors="replace")

            # Check if markers already exist
            pattern = re.compile(
                rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
                re.DOTALL,
            )

            if pattern.search(existing_text):
                # Replace marked section
                updated_text = pattern.sub(marked_block, existing_text)
                if updated_text == existing_text:
                    return SkillInstallResult(
                        agent_type=config.agent_type,
                        target_path=target_path,
                        action=SkillBridgeAction.UNCHANGED,
                        marker_present=True,
                        success=True,
                        details=f"Bridge configuration already up-to-date at {target_path}{conflict_msg}",
                    )
                target_path.write_text(updated_text, encoding="utf-8")
                return SkillInstallResult(
                    agent_type=config.agent_type,
                    target_path=target_path,
                    action=SkillBridgeAction.UPDATED,
                    marker_present=True,
                    success=True,
                    details=f"Updated existing bridge block at {target_path}{conflict_msg}",
                )

            # Append to existing content without touching original lines
            separator = "\n\n" if existing_text and not existing_text.endswith("\n\n") else ""
            appended_text = f"{existing_text}{separator}{marked_block}"
            target_path.write_text(appended_text, encoding="utf-8")
            return SkillInstallResult(
                agent_type=config.agent_type,
                target_path=target_path,
                action=SkillBridgeAction.UPDATED,
                marker_present=True,
                success=True,
                details=f"Appended bridge block to existing file at {target_path}{conflict_msg}",
            )
        except OSError as exc:
            return SkillInstallResult(
                agent_type=config.agent_type,
                target_path=target_path,
                action=SkillBridgeAction.UNCHANGED,
                marker_present=False,
                success=False,
                error=str(exc),
            )

    def uninstall(self, config: SkillInstallConfig) -> SkillUninstallResult:
        """Safely remove memory bridge instructions without altering user directives."""
        target_path = self._resolve_target_path(config)

        if not target_path.exists():
            return SkillUninstallResult(
                agent_type=config.agent_type,
                target_path=target_path,
                removed=False,
                file_deleted=False,
                success=True,
                details=f"File {target_path} does not exist. Nothing to remove.",
            )

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
            pattern = re.compile(
                rf"\n?{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
                re.DOTALL,
            )

            if not pattern.search(content):
                return SkillUninstallResult(
                    agent_type=config.agent_type,
                    target_path=target_path,
                    removed=False,
                    file_deleted=False,
                    success=True,
                    details=f"No bridge markers found in {target_path}. File left untouched.",
                )

            cleaned_content = pattern.sub("", content).strip()

            if not cleaned_content:
                # File only contained bridge block; remove cleanly
                target_path.unlink(missing_ok=True)
                return SkillUninstallResult(
                    agent_type=config.agent_type,
                    target_path=target_path,
                    removed=True,
                    file_deleted=True,
                    success=True,
                    details=f"Cleaned bridge block and removed empty file {target_path}",
                )

            # Preserve other user instructions
            target_path.write_text(f"{cleaned_content}\n", encoding="utf-8")
            return SkillUninstallResult(
                agent_type=config.agent_type,
                target_path=target_path,
                removed=True,
                file_deleted=False,
                success=True,
                details=f"Stripped bridge block from {target_path}; preserved user instructions",
            )
        except OSError as exc:
            return SkillUninstallResult(
                agent_type=config.agent_type,
                target_path=target_path,
                removed=False,
                file_deleted=False,
                success=False,
                error=str(exc),
            )
