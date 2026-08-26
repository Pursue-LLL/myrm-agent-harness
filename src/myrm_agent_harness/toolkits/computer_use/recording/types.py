"""
[INPUT]
- typing, dataclasses, enum, time

[OUTPUT]
- DesktopRecordedEvent, RecordedActionType, ToolLiftingCandidate, SynthesizedSkillStep, SynthesizedSkillDraft

[POS]
Data structures for Desktop Workflow Skill Recording, Event Clustering, Tool Lifting, and Skill Synthesis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RecordedActionType(str, Enum):
    """Types of recorded desktop actions."""

    CLICK = "click"
    TYPE = "type"
    KEY_PRESS = "key_press"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    WINDOW_FOCUS = "window_focus"
    APP_LAUNCH = "app_launch"
    CLIPBOARD_PASTE = "clipboard_paste"
    FILE_DROP = "file_drop"
    LIFTED_TOOL = "lifted_tool"


@dataclass
class DesktopRecordedEvent:
    """Individual recorded desktop interaction event."""

    seq: int
    timestamp: float = field(default_factory=time.time)
    action: str = RecordedActionType.CLICK.value
    app_name: str = ""
    bundle_id: str | None = None
    window_title: str = ""
    dref_id: str | None = None
    element_role: str | None = None
    element_title: str | None = None
    value: str | None = None
    is_password: bool = False
    modifiers: list[str] = field(default_factory=list)
    screenshot_b64: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "action": self.action,
            "app_name": self.app_name,
            "bundle_id": self.bundle_id,
            "window_title": self.window_title,
            "dref_id": self.dref_id,
            "element_role": self.element_role,
            "element_title": self.element_title,
            "value": "***" if self.is_password else self.value,
            "is_password": self.is_password,
            "modifiers": self.modifiers,
            "screenshot_b64": self.screenshot_b64,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DesktopRecordedEvent:
        """Create from dictionary."""
        return cls(
            seq=int(data.get("seq", 0)),
            timestamp=float(data.get("timestamp", time.time())),
            action=str(data.get("action", RecordedActionType.CLICK.value)),
            app_name=str(data.get("app_name", "")),
            bundle_id=data.get("bundle_id"),
            window_title=str(data.get("window_title", "")),
            dref_id=data.get("dref_id"),
            element_role=data.get("element_role"),
            element_title=data.get("element_title"),
            value=data.get("value"),
            is_password=bool(data.get("is_password", False)),
            modifiers=list(data.get("modifiers", [])),
            screenshot_b64=data.get("screenshot_b64"),
        )


@dataclass
class ToolLiftingCandidate:
    """A sequence of GUI events that can be lifted to a direct code or CLI tool invocation."""

    original_seqs: list[int]
    lifted_tool: str
    rationale: str
    code_snippet: str | None = None
    confidence: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_seqs": self.original_seqs,
            "lifted_tool": self.lifted_tool,
            "rationale": self.rationale,
            "code_snippet": self.code_snippet,
            "confidence": self.confidence,
        }


@dataclass
class SynthesizedSkillStep:
    """A synthesized, human-reviewable procedural step in the skill."""

    seq: int
    description: str
    action_type: str
    target_app: str
    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    variables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "description": self.description,
            "action_type": self.action_type,
            "target_app": self.target_app,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "variables": self.variables,
        }


@dataclass
class SynthesizedSkillDraft:
    """The complete synthesized skill draft ready for review and publishing."""

    skill_name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    parameters: list[dict[str, str]] = field(default_factory=list)
    steps: list[SynthesizedSkillStep] = field(default_factory=list)
    markdown_content: str = ""
    tool_lifting_applied: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "description": self.description,
            "triggers": self.triggers,
            "parameters": self.parameters,
            "steps": [s.to_dict() for s in self.steps],
            "markdown_content": self.markdown_content,
            "tool_lifting_applied": self.tool_lifting_applied,
            "created_at": self.created_at,
        }
