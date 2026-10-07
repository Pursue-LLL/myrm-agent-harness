"""Framework-bound standardized ClarifyTool implementation.

First-class built-in tool empowering agents to proactively ask clarifying questions,
resolve ambiguities, and eliminate hazardous blind guessing during execution.

[INPUT]
- toolkits.clarify.clarify_tool_types::ClarifyResolutionResult, ClarifyToolParams (POS: Data types and
  schemas for framework-bound clarify tool and ambiguity resolver.)

[OUTPUT]
- FrameworkBoundClarifyTool: Standardized framework-bound tool for interactive clarification and
  disambiguation.

[POS]
Framework-bound standardized ClarifyTool implementation.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from myrm_agent_harness.toolkits.clarify.clarify_tool_types import (
    ClarifyResolutionResult,
    ClarifyToolParams,
)


class FrameworkBoundClarifyTool:
    """Standardized framework-bound tool for interactive clarification and disambiguation."""

    name: str = "clarify_tool"
    description: str = (
        "Proactively ask the user a clarifying multiple-choice question when an instruction "
        "has ambiguous requirements, missing crucial parameters, or potential destructive risks. "
        "Never guess silently on dangerous or under-specified operations."
    )

    def get_tool_declaration(self) -> dict[str, object]:
        """Return standardized JSON Schema declaration for LLM tool binding."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Clear question describing the clarification needed.",
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "option_id": {"type": "string"},
                                "label": {"type": "string"},
                                "description": {"type": "string"},
                                "is_recommended": {"type": "boolean"},
                            },
                            "required": ["option_id", "label"],
                        },
                        "description": "Selectable structured options (at least 2 options).",
                    },
                    "allow_custom_input": {
                        "type": "boolean",
                        "description": "Whether to allow user write-in responses.",
                    },
                    "impact_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical_destructive"],
                    },
                },
                "required": ["question", "options"],
            },
        }

    def format_a2ui_card(self, params: ClarifyToolParams) -> dict[str, object]:
        """Format parameters into a standardized A2UI interactive clarification card payload."""
        options_payload = [
            {
                "optionId": opt.option_id,
                "label": opt.label,
                "description": opt.description,
                "isRecommended": opt.is_recommended,
            }
            for opt in params.options
        ]
        return {
            "component": "ClarifyQuestionCard",
            "version": "1.0",
            "impactLevel": params.impact_level.value,
            "category": params.category.value,
            "question": params.question,
            "options": options_payload,
            "allowCustomInput": params.allow_custom_input,
            "allowMultiple": params.allow_multiple,
        }

    def execute(
        self,
        params: ClarifyToolParams,
        resolution_handler: (
            Callable[[ClarifyToolParams], ClarifyResolutionResult] | None
        ) = None,
    ) -> str:
        """Execute clarification tool.

        If a resolution handler is provided (e.g. from UI response or test mock),
        formats the confirmed selection back to the model as deterministic tool output.
        Otherwise returns the serialized A2UI card awaiting user input.
        """
        if resolution_handler is not None:
            resolution = resolution_handler(params)
            return self.format_tool_result(params, resolution)

        card_payload = self.format_a2ui_card(params)
        return json.dumps(card_payload, ensure_ascii=False)

    def format_tool_result(
        self,
        params: ClarifyToolParams,
        resolution: ClarifyResolutionResult,
    ) -> str:
        """Format confirmed clarification resolution into an unambiguous tool result string."""
        opt_lookup = {opt.option_id: opt for opt in params.options}
        selected_labels: list[str] = []

        for o_id in resolution.selected_option_ids:
            if o_id in opt_lookup:
                selected_labels.append(opt_lookup[o_id].label)
            else:
                selected_labels.append(o_id)

        chosen_str = ", ".join(selected_labels) if selected_labels else "None"
        custom_str = f" (Custom note: '{resolution.custom_input}')" if resolution.custom_input else ""

        summary = (
            resolution.resolution_summary
            or f"User clarified and selected: [{chosen_str}]{custom_str}. Proceed strictly adhering to this choice."
        )
        return summary

    def create_automated_resolution(
        self,
        params: ClarifyToolParams,
        selected_option_id: str,
        custom_input: str | None = None,
    ) -> ClarifyResolutionResult:
        """Helper to create an immutable resolution result for testing or automation."""
        return ClarifyResolutionResult(
            selected_option_ids=(selected_option_id,),
            custom_input=custom_input,
            confirmed=True,
            resolution_summary="",
            timestamp=time.time(),
        )
