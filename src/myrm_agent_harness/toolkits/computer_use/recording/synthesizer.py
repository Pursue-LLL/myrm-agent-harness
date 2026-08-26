"""
[INPUT]
- .types::DesktopRecordedEvent, RecordedActionType, ToolLiftingCandidate, SynthesizedSkillStep, SynthesizedSkillDraft
- re, os, pathlib, time, typing

[OUTPUT]
- cluster_and_debounce_events, detect_tool_lifting_candidates, extract_parameter_slots, synthesize_desktop_skill_draft, render_skill_markdown

[POS]
Pure-algorithm synthesizer for desktop workflow recordings: event clustering, tool lifting, variable slot extraction, and SKILL.md rendering.
"""

from __future__ import annotations

import re
import time
from typing import Any

from .types import (
    DesktopRecordedEvent,
    RecordedActionType,
    SynthesizedSkillDraft,
    SynthesizedSkillStep,
    ToolLiftingCandidate,
)

_FILE_PATH_PATTERN = re.compile(
    r"([a-zA-Z]:\\[^\s\"\'<>|*?]+\.[a-zA-Z0-9]+|/(?:[^\s\"\'<>|*?]+/)+[^\s\"\'<>|*?]+\.[a-zA-Z0-9]+)"
)
_DATE_PATTERN = re.compile(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def cluster_and_debounce_events(
    events: list[DesktopRecordedEvent],
) -> list[DesktopRecordedEvent]:
    """Cluster consecutive keystrokes and debounce redundant focus/mouse events."""
    if not events:
        return []

    clustered: list[DesktopRecordedEvent] = []

    for ev in events:
        if not clustered:
            clustered.append(ev)
            continue

        prev = clustered[-1]

        # Merge consecutive typing on the same element / window
        if (
            ev.action == RecordedActionType.TYPE.value
            and prev.action == RecordedActionType.TYPE.value
            and ev.app_name == prev.app_name
            and ev.dref_id == prev.dref_id
            and not ev.is_password
            and not prev.is_password
        ):
            prev_val = prev.value or ""
            curr_val = ev.value or ""
            prev.value = prev_val + curr_val
            prev.timestamp = ev.timestamp
            continue

        # Skip redundant consecutive window focus events on the same window
        if (
            ev.action == RecordedActionType.WINDOW_FOCUS.value
            and prev.action == RecordedActionType.WINDOW_FOCUS.value
            and ev.app_name == prev.app_name
            and ev.window_title == prev.window_title
        ):
            continue

        clustered.append(ev)

    # Re-index sequences
    for idx, ev in enumerate(clustered, start=1):
        ev.seq = idx

    return clustered


def detect_tool_lifting_candidates(
    events: list[DesktopRecordedEvent],
) -> list[ToolLiftingCandidate]:
    """Identify sequences of GUI operations that can be elevated to robust code/CLI executions."""
    candidates: list[ToolLiftingCandidate] = []
    seq_window: list[DesktopRecordedEvent] = []

    for ev in events:
        app_lower = (ev.app_name or "").lower()
        title_lower = (ev.window_title or "").lower()

        # Terminal / Shell tool lifting
        if any(
            term in app_lower
            for term in ["terminal", "iterm", "cmd", "powershell", "alacritty", "kitty"]
        ):
            if ev.action == RecordedActionType.TYPE.value and ev.value:
                cmd = ev.value.strip()
                candidates.append(
                    ToolLiftingCandidate(
                        original_seqs=[ev.seq],
                        lifted_tool="shell_command",
                        rationale=f"Elevated terminal typing to native shell execution: '{cmd}'",
                        code_snippet=cmd,
                        confidence=0.98,
                    )
                )

        # File Editor / Text Editor tool lifting
        elif (
            any(ed in app_lower for ed in ["textedit", "notepad", "code", "sublime"])
            and ev.action == RecordedActionType.TYPE.value
        ):
            if ev.value and len(ev.value) > 10:
                candidates.append(
                    ToolLiftingCandidate(
                        original_seqs=[ev.seq],
                        lifted_tool="write_file",
                        rationale=f"Elevated text editing in {ev.app_name} to direct file write",
                        code_snippet=ev.value,
                        confidence=0.92,
                    )
                )

        # Excel / Spreadsheet manipulation tool lifting
        elif any(sheet in app_lower for sheet in ["excel", "wps", "calc", "numbers"]):
            if (
                ev.action == RecordedActionType.CLICK.value
                and "export" in (ev.element_title or "").lower()
            ):
                candidates.append(
                    ToolLiftingCandidate(
                        original_seqs=[ev.seq],
                        lifted_tool="execute_code",
                        rationale=f"Elevated Excel export in {ev.app_name} to Python pandas automation",
                        code_snippet="# Automated via Python pandas\nimport pandas as pd\n",
                        confidence=0.88,
                    )
                )

    return candidates


def extract_parameter_slots(events: list[DesktopRecordedEvent]) -> list[dict[str, str]]:
    """Extract variable slot opportunities from hardcoded strings, filepaths, and dates."""
    slots: dict[str, dict[str, str]] = {}

    for ev in events:
        val = ev.value or ""
        if not val or ev.is_password:
            continue

        # File paths
        fp_match = _FILE_PATH_PATTERN.search(val)
        if fp_match and "input_file_path" not in slots:
            slots["input_file_path"] = {
                "name": "input_file_path",
                "type": "string",
                "description": f"File path operand used in {ev.app_name}",
                "default_value": fp_match.group(1),
            }

        # Date values
        dt_match = _DATE_PATTERN.search(val)
        if dt_match and "target_date" not in slots:
            slots["target_date"] = {
                "name": "target_date",
                "type": "string",
                "description": f"Target date parameter used in {ev.app_name}",
                "default_value": dt_match.group(1),
            }

        # Email values
        em_match = _EMAIL_PATTERN.search(val)
        if em_match and "recipient_email" not in slots:
            slots["recipient_email"] = {
                "name": "recipient_email",
                "type": "string",
                "description": f"Email address used in {ev.app_name}",
                "default_value": em_match.group(0),
            }

    return list(slots.values())


def synthesize_desktop_skill_draft(
    events: list[DesktopRecordedEvent],
    skill_name: str,
    description: str = "",
) -> SynthesizedSkillDraft:
    """Synthesize a complete, structured skill draft from raw desktop events."""
    clustered = cluster_and_debounce_events(events)
    liftings = detect_tool_lifting_candidates(clustered)
    slots = extract_parameter_slots(clustered)

    lifting_map: dict[int, ToolLiftingCandidate] = {}
    for cand in liftings:
        for seq in cand.original_seqs:
            lifting_map[seq] = cand

    steps: list[SynthesizedSkillStep] = []
    step_seq = 1

    for ev in clustered:
        if ev.seq in lifting_map:
            cand = lifting_map[ev.seq]
            steps.append(
                SynthesizedSkillStep(
                    seq=step_seq,
                    description=cand.rationale,
                    action_type="lifted_tool",
                    target_app=ev.app_name or "System",
                    tool_name=cand.lifted_tool,
                    parameters={"snippet": cand.code_snippet or ""},
                    variables=[
                        s["name"]
                        for s in slots
                        if s["default_value"] in (cand.code_snippet or "")
                    ],
                )
            )
            step_seq += 1
            continue

        # Standard semantic desktop step
        step_desc = _format_step_description(ev)
        steps.append(
            SynthesizedSkillStep(
                seq=step_seq,
                description=step_desc,
                action_type="semantic_dref" if ev.dref_id else "gui_interaction",
                target_app=ev.app_name or "Desktop",
                tool_name=(
                    "desktop_interact_tool" if ev.dref_id else "desktop_snapshot_tool"
                ),
                parameters={
                    "dref": ev.dref_id or "",
                    "action": ev.action,
                    "value": ev.value or "",
                    "element_title": ev.element_title or "",
                },
                variables=[
                    s["name"] for s in slots if s["default_value"] in (ev.value or "")
                ],
            )
        )
        step_seq += 1

    formatted_name = skill_name.strip() or "desktop_workflow_skill"
    formatted_desc = (
        description.strip()
        or f"Automated workflow recorded from desktop activity across {', '.join({e.app_name for e in clustered if e.app_name}) or 'desktop applications'}."
    )

    draft = SynthesizedSkillDraft(
        skill_name=formatted_name,
        description=formatted_desc,
        triggers=[
            f"run {formatted_name}",
            f"execute {formatted_name}",
            f"automate {formatted_name}",
        ],
        parameters=slots,
        steps=steps,
        tool_lifting_applied=bool(liftings),
        created_at=time.time(),
    )

    draft.markdown_content = render_skill_markdown(draft)
    return draft


def _format_step_description(ev: DesktopRecordedEvent) -> str:
    """Format a human-readable description for a recorded event."""
    target = ev.element_title or ev.dref_id or ev.element_role or "target element"
    app = f"in {ev.app_name}" if ev.app_name else "on desktop"

    if ev.action == RecordedActionType.CLICK.value:
        return f"Click '{target}' {app}"
    elif ev.action == RecordedActionType.TYPE.value:
        masked_val = "***" if ev.is_password else (ev.value or "")
        return f"Enter '{masked_val}' into '{target}' {app}"
    elif ev.action == RecordedActionType.KEY_PRESS.value:
        return f"Press key '{ev.value}' {app}"
    elif ev.action == RecordedActionType.HOTKEY.value:
        keys = " + ".join(ev.modifiers + ([ev.value] if ev.value else []))
        return f"Trigger hotkey '{keys}' {app}"
    elif ev.action == RecordedActionType.WINDOW_FOCUS.value:
        return f"Switch focus to window '{ev.window_title}' ({ev.app_name})"
    else:
        return f"Perform {ev.action} on '{target}' {app}"


def render_skill_markdown(draft: SynthesizedSkillDraft) -> str:
    """Render a standard, production-ready SKILL.md file from a SynthesizedSkillDraft."""
    lines: list[str] = [
        "---",
        f"name: {draft.skill_name}",
        f'description: "{draft.description}"',
        "triggers:",
    ]
    for trg in draft.triggers:
        lines.append(f'  - "{trg}"')

    if draft.parameters:
        lines.append("parameters:")
        for p in draft.parameters:
            lines.append(f"  - name: {p['name']}")
            lines.append(f"    type: {p.get('type', 'string')}")
            lines.append(f"    description: \"{p.get('description', '')}\"")
            if "default_value" in p:
                lines.append(f"    default: \"{p['default_value']}\"")

    lines.append("---")
    lines.append("")
    lines.append(f"# {draft.skill_name}")
    lines.append("")
    lines.append(f"> {draft.description}")
    lines.append("")
    lines.append("## Workflow Execution Steps")
    lines.append("")

    for step in draft.steps:
        lines.append(f"### Step {step.seq}: {step.description}")
        lines.append(f"- **Target Application**: `{step.target_app}`")
        lines.append(f"- **Action Type**: `{step.action_type}`")
        lines.append(f"- **Tool**: `{step.tool_name}`")
        if step.parameters:
            for k, v in step.parameters.items():
                if v:
                    lines.append(f"  - `{k}`: `{v}`")
        if step.variables:
            lines.append(f"- **Variables**: `{', '.join(step.variables)}`")
        lines.append("")

    lines.append("## Verification & Quality Assurance")
    lines.append("1. Verify the final application state meets the expected outcome.")
    lines.append(
        "2. In case of UI element drift, fallback to `desktop_snapshot_tool` to re-resolve `@dref`."
    )
    lines.append("")

    return "\n".join(lines)
