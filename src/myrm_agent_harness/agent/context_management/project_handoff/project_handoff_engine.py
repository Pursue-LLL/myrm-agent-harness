"""Ten-Second Cross-Session Project Handoff and Zero-Context Re-Prompting Engine (Item 218).

[INPUT]
- workspace_root: Directory path or mock files dictionary.
- user_query: Natural language prompt triggering project handoff.
- ProjectHandoffConfig: Config controlling file paths and intent triggers.

[OUTPUT]
- ProjectWorkspaceDossier: Extracted avatar status dossier.
- HandoffHandshakeResponse: Instant structured handshake response aligning the AI in seconds.

[POS]
- Eliminates the need to re-explain project context upon new sessions or model switches
- by automatically aligning AI state from persistent workspace Markdown files.
"""

from __future__ import annotations

import os
import time

from ..dual_file_decoupling.dual_file_decoupling_engine import (
    DualFileProjectContextDecouplingEngine,
)
from .project_handoff_types import (
    HandoffHandshakeResponse,
    ProjectHandoffConfig,
    ProjectHandoffStatus,
    ProjectWorkspaceDossier,
)


class TenSecondProjectHandoffEngine:
    """Engine orchestrating zero-context session handoff and instant alignment handshake."""

    def __init__(self, config: ProjectHandoffConfig | None = None) -> None:
        self._config = config or ProjectHandoffConfig()
        self._decoupling_engine = DualFileProjectContextDecouplingEngine()

    @property
    def config(self) -> ProjectHandoffConfig:
        """Returns engine configuration."""
        return self._config

    def is_reprompt_handoff_intent(self, query_text: str) -> bool:
        """Detects whether user prompt intends to resume an existing project without background re-prompting."""
        if not self._config.enabled or not self._config.auto_detect_intent:
            return False

        q_lower = query_text.lower().strip()
        return any(kw.lower() in q_lower for kw in self._config.reprompt_intent_keywords)

    def sniff_workspace_dossier(
        self,
        workspace_root: str,
        files_map: dict[str, str] | None = None,
    ) -> ProjectWorkspaceDossier:
        """Scans workspace root (or in-memory mock map) to inspect project avatar readiness."""
        rules_name = self._config.rules_filename
        status_name = self._config.status_filename

        rules_content: str | None = None
        status_content: str | None = None

        if files_map is not None:
            rules_content = files_map.get(rules_name)
            status_content = files_map.get(status_name)
        else:
            rules_path = os.path.join(workspace_root, rules_name)
            if os.path.isfile(rules_path):
                try:
                    with open(rules_path, "r", encoding="utf-8") as rf:
                        rules_content = rf.read()
                except OSError:
                    rules_content = None

            status_path = os.path.join(workspace_root, status_name)
            if os.path.isfile(status_path):
                try:
                    with open(status_path, "r", encoding="utf-8") as sf:
                        status_content = sf.read()
                except OSError:
                    status_content = None

        rules_found = rules_content is not None
        status_found = status_content is not None

        if not rules_found and not status_found:
            return ProjectWorkspaceDossier(
                workspace_root=workspace_root,
                rules_file_found=False,
                status_file_found=False,
            )

        # Parse static rules if present
        principles_count = 0
        if rules_content:
            rule_spec = self._decoupling_engine.parse_static_rules(rules_content, rules_name)
            principles_count = len(rule_spec.core_principles) + len(rule_spec.forbidden_actions)

        # Parse dynamic overview status if present
        current_goal = ""
        deliverables_count = 0
        blockers: list[str] = []
        next_action = ""

        if status_content:
            sections = self._decoupling_engine.parse_dynamic_overview(status_content)
            current_goal = sections.current_phase_goal
            deliverables_count = len(sections.deliverables)
            blockers = list(sections.blockers_and_decisions)
            if sections.next_actions:
                next_action = sections.next_actions[0]

        return ProjectWorkspaceDossier(
            workspace_root=workspace_root,
            rules_file_found=rules_found,
            rules_file_path=rules_name,
            status_file_found=status_found,
            status_file_path=status_name,
            current_goal=current_goal or "项目持续推进中",
            rule_principles_count=principles_count,
            deliverables_count=deliverables_count,
            pending_blockers=blockers,
            suggested_next_action=next_action or "等待用户具体执行指令",
        )

    def generate_handshake_response(
        self,
        dossier: ProjectWorkspaceDossier,
    ) -> HandoffHandshakeResponse:
        """Generates structured, zero-fluff 10-second alignment handshake response."""
        start_time = time.perf_counter()

        if not dossier.rules_file_found and not dossier.status_file_found:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            msg = (
                "ℹ️ **未在当前工作区检测到项目分身文件**\n"
                f"未找到 `{self._config.rules_filename}` 或 `{self._config.status_filename}`。"
                "请先初始化项目规则与总览看板，或直接提出您的新需求。"
            )
            return HandoffHandshakeResponse(
                status=ProjectHandoffStatus.NO_AVATAR_DETECTED,
                handshake_markdown=msg,
                aligned_phase_goal="",
                suggested_next_action="",
                ready_for_execution=False,
                generation_duration_ms=duration_ms,
            )

        # Format blockers summary
        if dossier.pending_blockers and dossier.pending_blockers != ["无阻碍，进行中"]:
            blockers_summary = "; ".join(dossier.pending_blockers)
        else:
            blockers_summary = "无阻塞，各项前置准备均已就绪"

        handshake_lines: list[str] = [
            "🤝 **项目分身已就绪，当前工作现场已对齐**：",
            f"- 🎯 **当前阶段**：{dossier.current_goal}",
            f"- 📑 **核心规则与约束**：`{dossier.rules_file_path}`（{dossier.rule_principles_count} 条原则与红线已生效）",
            f"- ✅ **已确认成果**：已沉淀 {dossier.deliverables_count} 项阶段性产物",
            f"- ⚠️ **当前待决策事项**：{blockers_summary}",
            f"- 🚀 **下一步建议动作**：{dossier.suggested_next_action}",
            "",
            "已为您建立轻量冷启动上下文，是否立即开始执行下一步？",
        ]

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return HandoffHandshakeResponse(
            status=ProjectHandoffStatus.HANDSHAKE_COMPLETED,
            handshake_markdown="\n".join(handshake_lines),
            aligned_phase_goal=dossier.current_goal,
            suggested_next_action=dossier.suggested_next_action,
            ready_for_execution=True,
            generation_duration_ms=duration_ms,
        )
