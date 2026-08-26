"""Workflow skill compiler for desktop and multi-app user actions.

Provides data structures and deterministic compilation for converting recorded
desktop workflow sessions into structured, production-ready SKILL.md documents.
Maps high-level intent, ordered steps, and parameter variables into native agent
tool instructions.

[INPUT]
- DesktopEvent: Raw captured user activity event.
- WorkflowPlanStep: Semantic structured step in an analyzed plan.
- WorkflowIntentPlan: High-level intent plus ordered steps and variables.

[OUTPUT]
- compile_workflow_plan_to_skill_markdown: Generates complete SKILL.md content.
- WorkflowSkillCompiler: Facade with validation and tool mapping logic.

[POS]
Harness framework layer compiler for Desktop & Multi-App Workflow Skills.
Pure algorithmic and domain model - zero direct IO or runtime prompt mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


EventType = Literal[
    "app_switch",
    "clipboard_copy",
    "clipboard_paste",
    "navigation",
    "key_action",
    "file_interaction",
    "custom_step",
]

# Standard native tools recognized by MyrmAgent harness for workflow compilation.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "browser_navigate_tool",
    "browser_interact_tool",
    "browser_snapshot_tool",
    "browser_extract_tool",
    "shell_execute",
    "read_file",
    "write_file",
    "http_request",
)


@dataclass(slots=True)
class DesktopEvent:
    """Raw captured user desktop event during recording."""

    event_type: EventType
    timestamp_ms: int
    app_name: str = ""
    window_title: str = ""
    url: str = ""
    clipboard_preview: str = ""
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp_ms": self.timestamp_ms,
            "app_name": self.app_name,
            "window_title": self.window_title,
            "url": self.url,
            "clipboard_preview": self.clipboard_preview,
            "detail": self.detail,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DesktopEvent:
        return cls(
            event_type=data.get("event_type", "custom_step"),
            timestamp_ms=int(data.get("timestamp_ms", 0)),
            app_name=str(data.get("app_name", "")),
            window_title=str(data.get("window_title", "")),
            url=str(data.get("url", "")),
            clipboard_preview=str(data.get("clipboard_preview", "")),
            detail=str(data.get("detail", "")),
            extra=data.get("extra", {}) if isinstance(data.get("extra"), dict) else {},
        )


@dataclass(slots=True)
class WorkflowPlanStep:
    """A single semantic step in the reconstructed workflow plan."""

    step_id: str
    title: str
    description: str
    tool_hint: str = ""
    target_app: str = ""
    variables_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "tool_hint": self.tool_hint,
            "target_app": self.target_app,
            "variables_used": self.variables_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowPlanStep:
        return cls(
            step_id=str(data.get("step_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            tool_hint=str(data.get("tool_hint", "")),
            target_app=str(data.get("target_app", "")),
            variables_used=list(data.get("variables_used", [])),
        )


@dataclass(slots=True)
class WorkflowIntentPlan:
    """Reconstructed workflow plan containing intent, ordered steps, and variables."""

    name: str
    description: str
    intent: str
    steps: list[WorkflowPlanStep] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)  # var_name -> description/default
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "variables": self.variables,
            "allowed_tools": self.allowed_tools,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowIntentPlan:
        steps_raw = data.get("steps", [])
        steps = [WorkflowPlanStep.from_dict(s) for s in steps_raw if isinstance(s, dict)]
        return cls(
            name=str(data.get("name", "desktop-workflow-skill")),
            description=str(data.get("description", "")),
            intent=str(data.get("intent", "")),
            steps=steps,
            variables=data.get("variables", {}) if isinstance(data.get("variables"), dict) else {},
            allowed_tools=list(data.get("allowed_tools", list(DEFAULT_ALLOWED_TOOLS))),
        )


def slugify_skill_name(name: str) -> str:
    """Normalize a display name into a valid kebab-case skill identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\s]", "", name).strip().lower()
    slug = re.sub(r"[\s_]+", "-", cleaned)
    return slug or "desktop-workflow-skill"


def compile_workflow_plan_to_skill_markdown(plan: WorkflowIntentPlan) -> str:
    """Compile a WorkflowIntentPlan into standard, clean SKILL.md markdown.

    Produces frontmatter with name, description, version, and allowed-tools,
    followed by the goal intent, parameter placeholders, and ordered execution steps.
    """
    slug = slugify_skill_name(plan.name)
    desc = plan.description.strip() or f"Automated workflow for {plan.name}."
    tools_str = " ".join(plan.allowed_tools) if plan.allowed_tools else " ".join(DEFAULT_ALLOWED_TOOLS)

    lines: list[str] = [
        "---",
        f"name: {slug}",
        f"description: {desc}",
        "version: 1.0.0",
        f"allowed-tools: {tools_str}",
        "---",
        "",
        f"# {plan.name}",
        "",
        "## Overview",
        plan.intent.strip() or desc,
        "",
    ]

    if plan.variables:
        lines.append("## Parameters & Variables")
        lines.append("")
        for var_name, var_desc in plan.variables.items():
            lines.append(f"- `{{{{{var_name}}}}}`: {var_desc}")
        lines.append("")

    lines.append("## Execution Steps")
    lines.append("")
    for i, step in enumerate(plan.steps, start=1):
        step_header = f"### {i}. {step.title}"
        if step.target_app:
            step_header += f" (Target: {step.target_app})"
        lines.append(step_header)
        lines.append("")
        lines.append(step.description.strip())
        if step.tool_hint:
            lines.append(f"- **Suggested Tool**: `{step.tool_hint}`")
        if step.variables_used:
            vars_joined = ", ".join(f"`{{{{{v}}}}}`" for v in step.variables_used)
            lines.append(f"- **Variables Referenced**: {vars_joined}")
        lines.append("")

    lines.append("## Guidelines & Fallback")
    lines.append("- Prefer executing with native system tools (HTTP, CLI, file operations) when available.")
    lines.append("- Validate intermediate step outcomes before proceeding to subsequent mutations.")
    lines.append("- In case of unexpected UI state or API errors, report the exact error with context to the user.")
    lines.append("")

    return "\n".join(lines)


class WorkflowSkillCompiler:
    """Compiler facade for desktop workflow recordings."""

    @staticmethod
    def compile(plan: WorkflowIntentPlan) -> str:
        """Compile workflow intent plan to SKILL.md markdown text."""
        return compile_workflow_plan_to_skill_markdown(plan)

    @staticmethod
    def validate_plan(plan: WorkflowIntentPlan) -> list[str]:
        """Validate workflow intent plan integrity before compilation. Returns list of error messages."""
        errors: list[str] = []
        if not plan.name.strip():
            errors.append("Skill name cannot be empty.")
        if not plan.steps:
            errors.append("Workflow must contain at least one execution step.")
        for i, step in enumerate(plan.steps, start=1):
            if not step.title.strip():
                errors.append(f"Step {i} has empty title.")
            if not step.description.strip():
                errors.append(f"Step {i} has empty description.")
        return errors
