"""Strongly typed contracts for Ten-Second Cross-Session Project Handoff Protocol (Item 218).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ProjectHandoffStatus: Project avatar discovery and handshake status.
- ProjectWorkspaceDossier: Workspace avatar presence, parsed rules, and dynamic milestones.
- HandoffHandshakeResponse: Formatted 10-second instant alignment handshake message and state.
- ProjectHandoffConfig: Configuration governing file sniffers, intent keywords, and response templates.

[POS]
- Eliminates zero-context amnesia when starting new sessions or switching models by sniffing
- project files and aligning the AI with the project's exact active state in 10 seconds.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ProjectHandoffStatus(str, enum.Enum):
    """Lifecycle status of project avatar detection and handshake alignment."""

    NO_AVATAR_DETECTED = "no_avatar_detected"
    AVATAR_DETECTED_READY = "avatar_detected_ready"
    HANDSHAKE_COMPLETED = "handshake_completed"


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceDossier:
    """Strongly typed descriptor representing workspace avatar files and current state."""

    workspace_root: str
    rules_file_found: bool = False
    rules_file_path: str = "AGENTS.md"
    status_file_found: bool = False
    status_file_path: str = "00_项目总览.md"
    current_goal: str = ""
    rule_principles_count: int = 0
    deliverables_count: int = 0
    pending_blockers: list[str] = field(default_factory=list)
    suggested_next_action: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serializes workspace dossier to dictionary."""
        return {
            "workspace_root": self.workspace_root,
            "rules_file_found": self.rules_file_found,
            "rules_file_path": self.rules_file_path,
            "status_file_found": self.status_file_found,
            "status_file_path": self.status_file_path,
            "current_goal": self.current_goal,
            "rule_principles_count": self.rule_principles_count,
            "deliverables_count": self.deliverables_count,
            "pending_blockers": list(self.pending_blockers),
            "suggested_next_action": self.suggested_next_action,
        }


@dataclass(frozen=True, slots=True)
class HandoffHandshakeResponse:
    """Standardized 10-second instant alignment response generated for new sessions."""

    status: ProjectHandoffStatus
    handshake_markdown: str
    aligned_phase_goal: str
    suggested_next_action: str
    ready_for_execution: bool
    generation_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes handshake response to dictionary."""
        return {
            "status": self.status.value,
            "handshake_markdown": self.handshake_markdown,
            "aligned_phase_goal": self.aligned_phase_goal,
            "suggested_next_action": self.suggested_next_action,
            "ready_for_execution": self.ready_for_execution,
            "generation_duration_ms": self.generation_duration_ms,
        }


@dataclass(slots=True)
class ProjectHandoffConfig:
    """Configuration governing workspace file sniffing, handoff triggers, and responses."""

    enabled: bool = True
    rules_filename: str = "AGENTS.md"
    status_filename: str = "00_项目总览.md"
    auto_detect_intent: bool = True
    reprompt_intent_keywords: list[str] = field(
        default_factory=lambda: [
            "接手当前项目",
            "接手项目",
            "不要让我重复",
            "不要重复讲背景",
            "继续推进",
            "告诉我接下来该做什么",
            "按总览继续",
            "读取项目规则",
            "handoff",
            "resume project",
        ]
    )
