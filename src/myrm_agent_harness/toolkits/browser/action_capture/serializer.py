"""Serializer for capture sessions — converts ActionStep sequences to export formats.


[INPUT]
- types::CaptureSession, ActionStep (POS: captured session data)

[OUTPUT]
- serialize_session: Convert CaptureSession to JSON-serializable dict
- serialize_step: Convert single ActionStep to dict (for SSE streaming)
- steps_to_natural_language: Convert steps to human-readable description

[POS]
Handles serialization of capture data for API responses and SSE streaming.
Strips screenshot_b64 from full session exports to reduce payload size.
"""

from __future__ import annotations

from .types import ActionStep, CaptureSession


def serialize_step(step: ActionStep, *, include_screenshot: bool = False) -> dict[str, object]:
    """Serialize a single ActionStep for SSE streaming.

    Args:
        step: The captured action step.
        include_screenshot: Whether to include the base64 screenshot.

    Returns:
        JSON-serializable dictionary.
    """
    d: dict[str, object] = {
        "seq": step.seq,
        "action": step.action.value,
        "selector": step.selector,
        "value": step.value,
        "url": step.url,
        "title": step.title,
        "timestamp": step.timestamp,
        "element_text": step.element_text,
        "element_role": step.element_role,
        "is_password": step.is_password,
    }
    if include_screenshot and step.screenshot_b64:
        d["screenshot_b64"] = step.screenshot_b64
    return d


def serialize_session(session: CaptureSession, *, include_screenshots: bool = False) -> dict[str, object]:
    """Serialize a full CaptureSession.

    Args:
        session: The capture session.
        include_screenshots: Whether to include screenshots in step data.

    Returns:
        JSON-serializable dictionary.
    """
    return {
        "session_id": session.session_id,
        "status": session.status,
        "start_url": session.start_url,
        "start_time": session.start_time,
        "step_count": len(session.steps),
        "steps": [serialize_step(s, include_screenshot=include_screenshots) for s in session.steps],
    }


_ACTION_TEMPLATES: dict[str, str] = {
    "click": 'Click on "{element_text}" ({element_role})',
    "dblclick": 'Double-click on "{element_text}" ({element_role})',
    "type": 'Type "{value}" into {element_role}',
    "fill": 'Fill "{value}" into {element_role}',
    "select": 'Select "{value}" from dropdown',
    "check": "Check {element_text}",
    "uncheck": "Uncheck {element_text}",
    "navigate": "Navigate to {value}",
    "upload": 'Upload file(s): {value}',
    "press": "Press {value} key",
    "scroll": "Scroll page",
    "hover": 'Hover over "{element_text}"',
    "drag": "Drag element",
}


def step_to_natural_language(step: ActionStep) -> str:
    """Convert a single ActionStep to a human-readable sentence."""
    template = _ACTION_TEMPLATES.get(step.action.value, "Perform {action}")
    try:
        return template.format(
            element_text=step.element_text or step.selector,
            element_role=step.element_role,
            value=step.value,
            action=step.action.value,
        )
    except (KeyError, IndexError):
        return f"{step.action.value}: {step.selector}"


def steps_to_natural_language(steps: list[ActionStep]) -> str:
    """Convert a sequence of ActionSteps to a numbered description."""
    lines: list[str] = []
    for step in steps:
        lines.append(f"{step.seq}. {step_to_natural_language(step)}")
    return "\n".join(lines)
