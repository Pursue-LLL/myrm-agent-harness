"""Browser decision discipline rulebook and text output contract package.

[INPUT]
- decision_discipline_types: Core models and contract definitions.
- next_step_decision_rulebook: Action discipline prompts and evaluation guards.
- text_output_contract: Strict single-key text generation contract.
- browser_decision_discipline_suite: Orchestration facade.

[OUTPUT]
- Canonical exports for browser decision discipline subsystem.

[POS]
Modular implementation of browser next-step action discipline and structured text generation output contracts.
"""

from __future__ import annotations

from .browser_decision_discipline_suite import (
    BrowserNextStepDecisionRulebookAndTextOutputContractSuite,
)
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

__all__ = [
    "BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK",
    "BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK",
    "BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT",
    "BrowserActionKind",
    "BrowserNextStepDecisionRulebookAndTextOutputContractSuite",
    "DecisionEvaluationResult",
    "DisciplineRulebookConfig",
    "ElementState",
    "TextOutputContractResult",
    "parse_and_validate_text_contract",
    "validate_next_step_action",
    "validate_target_element",
]
