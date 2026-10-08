# [INPUT]: BrowserActionKind, DecisionEvaluationResult, DisciplineRulebookConfig, ElementState
# [OUTPUT]: BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK, BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK, validate_next_step_action, validate_target_element
# [POS]: toolkits/browser/decision_discipline/next_step_decision_rulebook.py

"""Browser next-step decision discipline rulebook and pre-flight validation guards.

[INPUT]
- BrowserActionKind, DecisionEvaluationResult, DisciplineRulebookConfig, ElementState:
  Domain types from decision_discipline_types.

[OUTPUT]
- BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK: Canonical system prompt instructing next action policy.
- BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK: Canonical system prompt instructing target selection.
- validate_next_step_action: Programmatic guard evaluating proposed next actions against discipline rules.
- validate_target_element: Programmatic guard validating candidate element selection.

[POS]
Decision discipline rulebook eliminating redundant steps, premature submits, abusive WAITs, and DONE hallucinations.
"""

from __future__ import annotations

from typing import Sequence

from .decision_discipline_types import (
    BrowserActionKind,
    DecisionEvaluationResult,
    DisciplineRulebookConfig,
    ElementState,
)

BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK: str = (
    "Advance the user's entire goal from the CURRENT page using one operation.\n"
    "Discipline Invariants:\n"
    "1. Do not repeat satisfied steps. Use current field values and action history.\n"
    "2. Fill required fields before submitting. A typed query still needs its matching "
    "autocomplete suggestion selected. For date pickers, CLICK the field, date, then confirmation.\n"
    "3. Set every requested filter/control; a matching result alone does not prove a requested filter was set.\n"
    "4. Do not toggle a checkbox, switch, or radio already in the requested state.\n"
    "5. Submit populated search fields before opening a result; a populated field alone is not an applied search.\n"
    "6. WAIT only when the needed control is absent/disabled, or submitted results are still loading.\n"
    "7. If Search/Submit is visible and the required fields are ready, CLICK it immediately.\n"
    "8. Recent WAIT actions are not evidence of loading. Prefer a useful visible control over WAIT.\n"
    "9. DONE requires visible evidence that ALL requirements are satisfied. If asked to open a result, "
    "a matching link is not enough. BLOCKED means no supported operation can make progress."
)

BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK: str = (
    "Choose the best observed target if the next operation is the one specified in this question.\n"
    "Target Invariants:\n"
    "1. Use the user's entire goal, field values, nearby text, and recent actions.\n"
    "2. Do not choose a field that already contains the requested value.\n"
    "3. Do not toggle an input whose state already matches the desired outcome.\n"
    "4. Choose only an offered element index from the valid candidate set."
)


def validate_next_step_action(
    action: BrowserActionKind,
    target_element: ElementState | None,
    desired_value: str | None = None,
    desired_checked_state: bool | None = None,
    unfilled_required_fields: Sequence[str] | None = None,
    page_is_loading: bool = False,
    recent_actions: Sequence[BrowserActionKind] = (),
    has_visible_done_evidence: bool = False,
    config: DisciplineRulebookConfig | None = None,
) -> DecisionEvaluationResult:
    """Validate proposed next action against decision disciplines before execution."""
    cfg = config or DisciplineRulebookConfig()

    # Rule 1: Anti-redundant toggle
    if action == BrowserActionKind.CLICK and target_element is not None:
        if target_element.role in ("checkbox", "switch", "radio"):
            if (
                desired_checked_state is not None
                and target_element.checked is not None
                and target_element.checked == desired_checked_state
            ):
                return DecisionEvaluationResult(
                    valid=False,
                    violation_code="REDUNDANT_TOGGLE",
                    reason=(
                        f"Element [{target_element.index}] '{target_element.label}' is already in "
                        f"the requested checked state ({desired_checked_state}). Toggling would revert it."
                    ),
                    suggested_action="Proceed to subsequent field or next required operation",
                )

    # Rule 2: Anti-redundant type text
    if action == BrowserActionKind.TYPE_TEXT and target_element is not None:
        if (
            desired_value is not None
            and target_element.current_value.strip() == desired_value.strip()
            and desired_value.strip() != ""
        ):
            return DecisionEvaluationResult(
                valid=False,
                violation_code="REDUNDANT_TYPE",
                reason=(
                    f"Element [{target_element.index}] '{target_element.label}' already contains "
                    f"the requested value '{desired_value}'. Typing again is redundant."
                ),
                suggested_action="Advance to submit control or next required input",
            )

    # Rule 3: Premature submission
    if action == BrowserActionKind.CLICK and target_element is not None:
        is_submit_button = (
            target_element.role == "button"
            and any(term in target_element.label.lower() for term in ("submit", "search", "apply", "commit"))
        )
        if is_submit_button and unfilled_required_fields:
            missing = ", ".join(unfilled_required_fields)
            return DecisionEvaluationResult(
                valid=False,
                violation_code="PREMATURE_SUBMIT",
                reason=(
                    f"Submitting form prematurely while required fields are not yet populated: {missing}."
                ),
                suggested_action=f"Populate required field: {unfilled_required_fields[0]}",
            )

    # Rule 4: Abusive WAIT and history WAIT bias
    if action == BrowserActionKind.WAIT:
        consecutive_waits = 0
        for act in reversed(recent_actions):
            if act == BrowserActionKind.WAIT:
                consecutive_waits += 1
            else:
                break

        if consecutive_waits >= cfg.max_consecutive_wait and not page_is_loading:
            return DecisionEvaluationResult(
                valid=False,
                violation_code="ABUSIVE_WAIT",
                reason=(
                    f"Exceeded maximum consecutive WAIT limit ({cfg.max_consecutive_wait}) without active loading indicators. "
                    "Recent WAIT actions are not evidence of loading. Prefer a useful visible control over WAIT."
                ),
                suggested_action="Select an available interactive element or declare BLOCKED",
            )

    # Rule 5: Premature DONE without visible evidence
    if action == BrowserActionKind.DONE and cfg.require_visible_evidence_for_done:
        if not has_visible_done_evidence:
            return DecisionEvaluationResult(
                valid=False,
                violation_code="UNSUBSTANTIATED_DONE",
                reason=(
                    "DONE requires visible evidence that ALL requirements are satisfied. "
                    "A matching link or unverified preview alone is not sufficient."
                ),
                suggested_action="Verify result details or complete final confirmation step",
            )

    return DecisionEvaluationResult(valid=True)


def validate_target_element(
    target_index: int,
    available_elements: Sequence[ElementState],
) -> DecisionEvaluationResult:
    """Validate that target element index is offered and interactable."""
    element_map = {el.index: el for el in available_elements}
    if target_index not in element_map:
        return DecisionEvaluationResult(
            valid=False,
            violation_code="INVALID_TARGET_INDEX",
            reason=f"Element index [{target_index}] is not among offered candidates",
            suggested_action="Select only an index present in the offered candidates list",
        )

    target = element_map[target_index]
    if target.disabled:
        return DecisionEvaluationResult(
            valid=False,
            violation_code="DISABLED_TARGET_ELEMENT",
            reason=f"Element [{target_index}] '{target.label}' is disabled and cannot accept interactions",
            suggested_action="Wait for control to become enabled or select alternate element",
        )

    return DecisionEvaluationResult(valid=True)
