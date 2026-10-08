# [INPUT]: None
# [OUTPUT]: BrowserActionKind, ElementState, DecisionEvaluationResult, TextOutputContractResult, DisciplineRulebookConfig
# [POS]: toolkits/browser/decision_discipline/decision_discipline_types.py

"""Domain contracts and models for browser next-step decision discipline and text output contracts.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- BrowserActionKind: Discrete primitive browser operation kinds.
- ElementState: Observed state snapshot of a target browser DOM/AX element.
- DecisionEvaluationResult: Validation verdict for browser action proposals.
- TextOutputContractResult: Verification outcome for single-key text generation JSON responses.
- DisciplineRulebookConfig: Configuration governing anti-looping and strict verification thresholds.

[POS]
Domain models for browser agent operational discipline and structured text generation constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class BrowserActionKind(str, Enum):
    """Primitive browser action kinds evaluated under the decision discipline."""

    CLICK = "CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    SELECT = "SELECT"
    WAIT = "WAIT"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ElementState:
    """Observed state of an interactive page element evaluated by the discipline guard."""

    index: int
    role: str
    label: str
    current_value: str = ""
    checked: bool | None = None
    selected: bool | None = None
    expanded: bool | None = None
    disabled: bool = False
    visible: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionEvaluationResult:
    """Evaluation verdict assessing whether a proposed next action satisfies decision disciplines."""

    valid: bool
    violation_code: str | None = None
    reason: str | None = None
    suggested_action: str | None = None


@dataclass(frozen=True)
class TextOutputContractResult:
    """Outcome of validating LLM helper output against the single-key text contract."""

    valid: bool
    extracted_text: str | None = None
    is_null: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class DisciplineRulebookConfig:
    """Configuration governing browser decision discipline thresholds."""

    max_consecutive_wait: int = 2
    require_visible_evidence_for_done: bool = True
    enforce_strict_text_contract: bool = True
