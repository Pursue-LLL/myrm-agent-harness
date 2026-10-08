"""Comprehensive facade suite for browser decision discipline rulebooks and text output contracts.

[INPUT]
- BrowserActionKind, DecisionEvaluationResult, DisciplineRulebookConfig, ElementState, TextOutputContractResult:
  Domain types from decision_discipline_types.

[OUTPUT]
- BrowserNextStepDecisionRulebookAndTextOutputContractSuite: Central facade managing prompt injection,
  pre-flight action discipline evaluation, target selection validation, and text output contracts.

[POS]
Top-level entrypoint for browser agent decision discipline and text contract compliance.
"""

from __future__ import annotations

from typing import Sequence

from .decision_discipline_types import (
    BrowserActionKind,
    DecisionEvaluationResult,
    DisciplineRulebookConfig,
    ElementState,
    TextOutputContractResult,
)
from .next_step_decision_rulebook import (
    BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK,
    BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK,
    validate_next_step_action,
    validate_target_element,
)
from .text_output_contract import (
    BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT,
    parse_and_validate_text_contract,
)


class BrowserNextStepDecisionRulebookAndTextOutputContractSuite:
    """Orchestrates decision discipline rules, target selection guards, and text output contracts."""

    def __init__(self, config: DisciplineRulebookConfig | None = None) -> None:
        self._config = config or DisciplineRulebookConfig()

    @property
    def config(self) -> DisciplineRulebookConfig:
        return self._config

    @staticmethod
    def get_next_action_rules() -> str:
        """Return canonical next action discipline rulebook prompt."""
        return BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK

    @staticmethod
    def get_target_selection_rules() -> str:
        """Return canonical target selection discipline rulebook prompt."""
        return BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK

    @staticmethod
    def get_text_contract_rules() -> str:
        """Return canonical text generation single-key contract prompt."""
        return BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT

    def inject_discipline_into_prompt(
        self,
        base_prompt: str,
        include_target_rules: bool = True,
        include_text_contract: bool = True,
    ) -> str:
        """Inject structured discipline rules and output contracts into agent system prompts."""
        sections: list[str] = [base_prompt.strip()]
        sections.append(
            f"### [BROWSER DECISION DISCIPLINE: NEXT ACTION]\n{BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK}"
        )

        if include_target_rules:
            sections.append(
                f"### [BROWSER DECISION DISCIPLINE: TARGET SELECTION]\n{BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK}"
            )

        if include_text_contract:
            sections.append(
                f"### [BROWSER OUTPUT CONTRACT: TEXT VALUE]\n{BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT}"
            )

        return "\n\n".join(sections)

    def validate_action(
        self,
        action: BrowserActionKind,
        target_element: ElementState | None = None,
        desired_value: str | None = None,
        desired_checked_state: bool | None = None,
        unfilled_required_fields: Sequence[str] | None = None,
        page_is_loading: bool = False,
        recent_actions: Sequence[BrowserActionKind] = (),
        has_visible_done_evidence: bool = False,
    ) -> DecisionEvaluationResult:
        """Validate proposed browser action against the discipline rulebook before execution."""
        return validate_next_step_action(
            action=action,
            target_element=target_element,
            desired_value=desired_value,
            desired_checked_state=desired_checked_state,
            unfilled_required_fields=unfilled_required_fields,
            page_is_loading=page_is_loading,
            recent_actions=recent_actions,
            has_visible_done_evidence=has_visible_done_evidence,
            config=self._config,
        )

    def validate_target(
        self,
        target_index: int,
        available_elements: Sequence[ElementState],
    ) -> DecisionEvaluationResult:
        """Validate candidate element target index."""
        return validate_target_element(
            target_index=target_index,
            available_elements=available_elements,
        )

    def validate_text_output(
        self,
        raw_response: str,
    ) -> TextOutputContractResult:
        """Validate that LLM text response adheres to the single-key {'text': ...} contract."""
        return parse_and_validate_text_contract(raw_response)

    @classmethod
    def create(
        cls,
        config: DisciplineRulebookConfig | None = None,
    ) -> BrowserNextStepDecisionRulebookAndTextOutputContractSuite:
        """Create a default suite instance."""
        return cls(config)
