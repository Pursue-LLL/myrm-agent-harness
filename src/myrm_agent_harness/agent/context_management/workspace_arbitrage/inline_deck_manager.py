"""Inline work-in-chat deck manager for micro interactive widgets.

[INPUT]
- arbitrage_types: DeckWidgetSpec, DeckWidgetType, DeckWidgetState,
  DeckInteractionEvent, DeckActionResult.

[OUTPUT]
- InlineDeckManager: Registers, transitions, interacts, and projects
  compact context summaries of inline widgets.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: inline_deck_manager.py
"""

from typing import Dict, List, Mapping, Optional, Sequence
from myrm_agent_harness.agent.context_management.workspace_arbitrage.arbitrage_types import (
    DeckActionResult,
    DeckInteractionEvent,
    DeckWidgetSpec,
    DeckWidgetState,
    DeckWidgetType,
)


class InlineDeckManager:
    """Manages conversational inline interactive widgets embedded within chat messages."""

    def __init__(self) -> None:
        self._widgets: Dict[str, DeckWidgetSpec] = {}
        self._message_widget_index: Dict[str, List[str]] = {}

    def register_widget(self, spec: DeckWidgetSpec) -> DeckWidgetSpec:
        """Registers a new inline interactive widget under a given message.

        Args:
            spec: The immutable widget specification.

        Returns:
            The registered widget specification.
        """
        self._widgets[spec.widget_id] = spec
        if spec.message_id not in self._message_widget_index:
            self._message_widget_index[spec.message_id] = []
        if spec.widget_id not in self._message_widget_index[spec.message_id]:
            self._message_widget_index[spec.message_id].append(spec.widget_id)
        return spec

    def get_widget(self, widget_id: str) -> Optional[DeckWidgetSpec]:
        """Retrieves a registered widget by its identifier."""
        return self._widgets.get(widget_id)

    def list_widgets_for_message(self, message_id: str) -> Sequence[DeckWidgetSpec]:
        """Returns all widgets registered under a given message."""
        widget_ids = self._message_widget_index.get(message_id, [])
        return tuple(self._widgets[wid] for wid in widget_ids if wid in self._widgets)

    def list_all_widgets(self) -> Sequence[DeckWidgetSpec]:
        """Returns all registered widgets across all messages."""
        return tuple(self._widgets.values())

    def handle_interaction(self, event: DeckInteractionEvent) -> DeckActionResult:
        """Processes a user interaction dispatched from an inline widget.

        Args:
            event: The interaction payload and action.

        Returns:
            DeckActionResult indicating the result and updated state.
        """
        spec = self._widgets.get(event.widget_id)
        if spec is None:
            return DeckActionResult(
                widget_id=event.widget_id,
                new_state=DeckWidgetState.REJECTED,
                feedback_message=f"Widget '{event.widget_id}' not found.",
                success=False,
            )

        action = event.action_name.lower().strip()
        new_state = spec.state
        feedback = "Action processed."
        result_payload: Dict[str, str] = dict(event.parameters)

        if spec.widget_type == DeckWidgetType.STEP_APPROVAL:
            if action in ("approve", "confirm", "accept"):
                new_state = DeckWidgetState.APPROVED
                feedback = f"Step approved: {spec.title}"
            elif action in ("reject", "cancel", "deny"):
                new_state = DeckWidgetState.REJECTED
                feedback = f"Step rejected: {spec.title}"
            else:
                feedback = f"Unknown approval action '{action}'."
        elif spec.widget_type == DeckWidgetType.PARAM_SLIDER:
            new_state = DeckWidgetState.ACTIVE
            feedback = f"Parameter updated for {spec.title}"
        elif spec.widget_type == DeckWidgetType.DIFF_VIEW:
            if action in ("apply_diff", "merge"):
                new_state = DeckWidgetState.EXECUTED
                feedback = f"Diff applied: {spec.title}"
            elif action in ("discard", "dismiss"):
                new_state = DeckWidgetState.REJECTED
                feedback = f"Diff discarded: {spec.title}"
            else:
                new_state = DeckWidgetState.ACTIVE
                feedback = f"Diff viewed: {spec.title}"
        elif spec.widget_type == DeckWidgetType.MICRO_TERMINAL:
            if action in ("run", "execute"):
                new_state = DeckWidgetState.EXECUTED
                feedback = f"Terminal command executed for {spec.title}"
            else:
                new_state = DeckWidgetState.ACTIVE
                feedback = f"Terminal interactive step for {spec.title}"

        # Update the widget with updated state
        updated_spec = DeckWidgetSpec(
            widget_id=spec.widget_id,
            message_id=spec.message_id,
            widget_type=spec.widget_type,
            title=spec.title,
            initial_payload=spec.initial_payload,
            state=new_state,
            created_at_epoch=spec.created_at_epoch,
        )
        self._widgets[spec.widget_id] = updated_spec

        return DeckActionResult(
            widget_id=spec.widget_id,
            new_state=new_state,
            feedback_message=feedback,
            result_payload=result_payload,
            success=True,
        )

    def render_context_summary(self, max_items: int = 5) -> str:
        """Renders a compact, high signal-to-noise context projection of active widgets.

        Ensures full conversational flow context without blowing up the token window.

        Args:
            max_items: Maximum number of recent widgets to include.

        Returns:
            A clean formatted markdown block suitable for prompt injection.
        """
        if not self._widgets:
            return ""

        recent = list(self._widgets.values())[-max_items:]
        lines: List[str] = ["[INLINE_WORK_DECK_STATUS]"]
        for w in recent:
            lines.append(
                f"- Widget [{w.widget_id}] Type={w.widget_type.value} "
                f"Title='{w.title}' State={w.state.value}"
            )
        lines.append("[/INLINE_WORK_DECK_STATUS]")
        return "\n".join(lines)
