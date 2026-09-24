"""
[INPUT]
- .types::DesktopRecordedEvent, RecordedActionType, ToolLiftingCandidate, SynthesizedSkillStep, SynthesizedSkillDraft
- .synthesizer::cluster_and_debounce_events, detect_tool_lifting_candidates, extract_parameter_slots, synthesize_desktop_skill_draft, render_skill_markdown
- .capture_driver::DesktopCaptureDriver, CaptureFrame

[OUTPUT]
- DesktopRecordedEvent, RecordedActionType, ToolLiftingCandidate, SynthesizedSkillStep, SynthesizedSkillDraft, cluster_and_debounce_events, detect_tool_lifting_candidates, extract_parameter_slots, synthesize_desktop_skill_draft, render_skill_markdown, DesktopCaptureDriver, CaptureFrame

[POS]
Desktop workflow recording and skill synthesis module.
"""

from __future__ import annotations

from .capture_driver import CaptureFrame, DesktopCaptureDriver
from .synthesizer import (
    cluster_and_debounce_events,
    detect_tool_lifting_candidates,
    extract_parameter_slots,
    render_skill_markdown,
    synthesize_desktop_skill_draft,
)
from .types import (
    DesktopRecordedEvent,
    RecordedActionType,
    SynthesizedSkillDraft,
    SynthesizedSkillStep,
    ToolLiftingCandidate,
)

__all__ = [
    "CaptureFrame",
    "DesktopCaptureDriver",
    "DesktopRecordedEvent",
    "RecordedActionType",
    "SynthesizedSkillDraft",
    "SynthesizedSkillStep",
    "ToolLiftingCandidate",
    "cluster_and_debounce_events",
    "detect_tool_lifting_candidates",
    "extract_parameter_slots",
    "render_skill_markdown",
    "synthesize_desktop_skill_draft",
]
