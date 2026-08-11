"""Serializer for capture sessions — converts ActionStep sequences to export formats.


[INPUT]
- types::CaptureSession, ActionStep (POS: captured session data)

[OUTPUT]
- serialize_session: Convert CaptureSession to JSON-serializable dict
- serialize_step: Convert single ActionStep to dict (for SSE streaming)
- step_to_natural_language: Convert one ActionStep to a natural-language sentence; emits `fill_credential` directives for credential-labeled steps
- steps_to_natural_language: Convert a step sequence to numbered natural-language instructions, honoring per-step credential labels

[POS]
Handles serialization of capture data for API responses and SSE streaming.
Strips screenshot_b64 from full session exports to reduce payload size.
"""

from __future__ import annotations

from .types import ActionStep, ActionType, CaptureSession


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
        "modifiers": list(step.modifiers),
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
    "type": 'Type "{value}" into {element_context}',
    "fill": 'Fill "{value}" into {element_context}',
    "select": 'Select "{value}" from dropdown',
    "check": "Check {element_text}",
    "uncheck": "Uncheck {element_text}",
    "navigate": "Navigate to {value}",
    "upload": "Upload file(s): {value}",
    "scroll": "Scroll page",
    "hover": 'Hover over "{element_text}"',
    "drag": "Drag element",
}

# Steps whose template needs a disambiguating element context (multi-input forms).
_CONTEXT_TEMPLATES = frozenset({"fill", "type"})


def _element_context(step: ActionStep) -> str:
    """Build an element description that disambiguates fill/type targets.

    Prefers the captured text (aria-label/placeholder) and falls back to the
    selector so the agent can tell input fields apart on multi-field forms.
    """
    text = step.element_text or step.selector
    role = step.element_role or "element"
    return f'{role} "{text}"' if text else role


def step_to_natural_language(step: ActionStep, *, credential_label: str | None = None) -> str:
    """Convert a single ActionStep to a human-readable sentence.

    Args:
        step: The captured action step.
        credential_label: When the step targets a password/sensitive field,
            emit a `fill_credential` directive instead of the masked value so
            the agent pulls the real secret from CredentialVault. Ignored for
            non-sensitive steps to keep the API misuse-proof.
    """
    if credential_label and step.is_password:
        return f'Fill credential "{credential_label}" into {_element_context(step)}'
    if step.action == ActionType.PRESS:
        key = step.value.title()
        if step.modifiers:
            mods = "+".join(m.title() for m in step.modifiers)
            return f"Press {mods}+{key}"
        return f"Press {key}"
    template = _ACTION_TEMPLATES.get(step.action.value, "Perform {action}")
    try:
        return template.format(
            element_text=step.element_text or step.selector,
            element_role=step.element_role,
            element_context=_element_context(step)
            if step.action.value in _CONTEXT_TEMPLATES
            else "",
            value=step.value,
            action=step.action.value,
        )
    except (KeyError, IndexError):
        return f"{step.action.value}: {step.selector}"


def steps_to_natural_language(
    steps: list[ActionStep],
    credential_labels: dict[int, str] | None = None,
) -> str:
    """Convert a sequence of ActionSteps to a numbered description.

    Args:
        steps: The captured action steps.
        credential_labels: Optional mapping of step seq -> CredentialVault label;
            matching steps are rendered as `fill_credential` directives.
    """
    labels = credential_labels or {}
    lines: list[str] = []
    for step in steps:
        lines.append(
            f"{step.seq}. {step_to_natural_language(step, credential_label=labels.get(step.seq))}"
        )
    return "\n".join(lines)
