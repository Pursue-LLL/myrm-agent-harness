# [INPUT]: BrowserActionKind, BrowserNextStepDecisionRulebookAndTextOutputContractSuite, DisciplineRulebookConfig, ElementState
# [OUTPUT]: test_decision_discipline_suite.py
# [POS]: tests/toolkits/browser/test_decision_discipline_suite.py

"""Comprehensive test suite for BrowserNextStepDecisionRulebookAndTextOutputContractSuite.

Verifies:
1. Anti-redundant toggle and anti-redundant typing guards.
2. Premature form submission prevention when required fields are missing.
3. Abusive WAIT limitation (history WAIT bias mitigation) and DONE visible evidence enforcement.
4. Target element validity checks and strict single-key {'text': ...} output contract compliance.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.decision_discipline import (
    BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK,
    BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK,
    BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT,
    BrowserActionKind,
    BrowserNextStepDecisionRulebookAndTextOutputContractSuite,
    DecisionEvaluationResult,
    DisciplineRulebookConfig,
    ElementState,
    TextOutputContractResult,
    parse_and_validate_text_contract,
    validate_next_step_action,
    validate_target_element,
)


def test_anti_redundant_toggle_and_type_guards() -> None:
    suite = BrowserNextStepDecisionRulebookAndTextOutputContractSuite()

    # Case 1: Checkbox already in target checked state
    checkbox = ElementState(
        index=10,
        role="checkbox",
        label="Accept Terms",
        checked=True,
    )
    result_toggle = suite.validate_action(
        action=BrowserActionKind.CLICK,
        target_element=checkbox,
        desired_checked_state=True,
    )
    assert not result_toggle.valid
    assert result_toggle.violation_code == "REDUNDANT_TOGGLE"
    assert "already in the requested checked state" in (result_toggle.reason or "")

    # Checkbox in different state: allowed
    result_toggle_ok = suite.validate_action(
        action=BrowserActionKind.CLICK,
        target_element=checkbox,
        desired_checked_state=False,
    )
    assert result_toggle_ok.valid

    # Case 2: Input field already contains the desired value
    text_input = ElementState(
        index=11,
        role="textbox",
        label="Search Query",
        current_value="tokyo hotel",
    )
    result_type = suite.validate_action(
        action=BrowserActionKind.TYPE_TEXT,
        target_element=text_input,
        desired_value="tokyo hotel",
    )
    assert not result_type.valid
    assert result_type.violation_code == "REDUNDANT_TYPE"
    assert "already contains the requested value" in (result_type.reason or "")

    # Input field with different value: allowed
    result_type_ok = suite.validate_action(
        action=BrowserActionKind.TYPE_TEXT,
        target_element=text_input,
        desired_value="kyoto hotel",
    )
    assert result_type_ok.valid


def test_premature_submission_prevention() -> None:
    suite = BrowserNextStepDecisionRulebookAndTextOutputContractSuite()

    submit_button = ElementState(
        index=20,
        role="button",
        label="Submit Application",
    )

    # Has unfilled required fields: reject submit click
    res_premature = suite.validate_action(
        action=BrowserActionKind.CLICK,
        target_element=submit_button,
        unfilled_required_fields=["Passport Number", "Arrival Date"],
    )
    assert not res_premature.valid
    assert res_premature.violation_code == "PREMATURE_SUBMIT"
    assert "Passport Number, Arrival Date" in (res_premature.reason or "")

    # All required fields filled: allowed
    res_ok = suite.validate_action(
        action=BrowserActionKind.CLICK,
        target_element=submit_button,
        unfilled_required_fields=[],
    )
    assert res_ok.valid


def test_abusive_wait_and_done_visible_evidence_guards() -> None:
    suite = BrowserNextStepDecisionRulebookAndTextOutputContractSuite(
        config=DisciplineRulebookConfig(max_consecutive_wait=2, require_visible_evidence_for_done=True)
    )

    # Case 1: Exceeded consecutive WAIT without loading state
    history_with_waits = [
        BrowserActionKind.TYPE_TEXT,
        BrowserActionKind.WAIT,
        BrowserActionKind.WAIT,
    ]
    res_wait_blocked = suite.validate_action(
        action=BrowserActionKind.WAIT,
        recent_actions=history_with_waits,
        page_is_loading=False,
    )
    assert not res_wait_blocked.valid
    assert res_wait_blocked.violation_code == "ABUSIVE_WAIT"
    assert "Recent WAIT actions are not evidence of loading" in (res_wait_blocked.reason or "")

    # Page is actively loading: WAIT permitted
    res_wait_allowed = suite.validate_action(
        action=BrowserActionKind.WAIT,
        recent_actions=history_with_waits,
        page_is_loading=True,
    )
    assert res_wait_allowed.valid

    # Case 2: Premature DONE without visible confirmation evidence
    res_done_unsubstantiated = suite.validate_action(
        action=BrowserActionKind.DONE,
        has_visible_done_evidence=False,
    )
    assert not res_done_unsubstantiated.valid
    assert res_done_unsubstantiated.violation_code == "UNSUBSTANTIATED_DONE"

    # DONE with visible confirmation evidence: allowed
    res_done_ok = suite.validate_action(
        action=BrowserActionKind.DONE,
        has_visible_done_evidence=True,
    )
    assert res_done_ok.valid


def test_target_validation_and_prompt_injection() -> None:
    suite = BrowserNextStepDecisionRulebookAndTextOutputContractSuite.create()

    candidates = [
        ElementState(index=1, role="button", label="Next", disabled=False),
        ElementState(index=2, role="button", label="Cancel", disabled=True),
    ]

    # Valid candidate
    assert suite.validate_target(1, candidates).valid

    # Disabled candidate
    res_disabled = suite.validate_target(2, candidates)
    assert not res_disabled.valid
    assert res_disabled.violation_code == "DISABLED_TARGET_ELEMENT"

    # Missing candidate index
    res_missing = suite.validate_target(99, candidates)
    assert not res_missing.valid
    assert res_missing.violation_code == "INVALID_TARGET_INDEX"

    # Prompt injection check
    base_prompt = "You are a web automation agent."
    injected = suite.inject_discipline_into_prompt(base_prompt)
    assert "[BROWSER DECISION DISCIPLINE: NEXT ACTION]" in injected
    assert "[BROWSER DECISION DISCIPLINE: TARGET SELECTION]" in injected
    assert "[BROWSER OUTPUT CONTRACT: TEXT VALUE]" in injected
    assert suite.get_next_action_rules() == BROWSER_NEXT_ACTION_DISCIPLINE_RULEBOOK
    assert suite.get_target_selection_rules() == BROWSER_TARGET_SELECTION_DISCIPLINE_RULEBOOK
    assert suite.get_text_contract_rules() == BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT


def test_strict_single_key_text_output_contract() -> None:
    suite = BrowserNextStepDecisionRulebookAndTextOutputContractSuite()

    # Case 1: Pure valid JSON with single text key
    res_valid = suite.validate_text_output('{"text": "John Doe"}')
    assert res_valid.valid
    assert res_valid.extracted_text == "John Doe"
    assert not res_valid.is_null

    # Case 2: Markdown codeblock unwrapping
    res_codeblock = suite.validate_text_output('```json\n{"text": "123 Main St"}\n```')
    assert res_codeblock.valid
    assert res_codeblock.extracted_text == "123 Main St"

    # Case 3: Explicit null value when required field missing
    res_null = suite.validate_text_output('{"text": null}')
    assert res_null.valid
    assert res_null.is_null
    assert res_null.extracted_text is None

    # Case 4: Violation - Extraneous keys / chatter
    res_extra_keys = suite.validate_text_output('{"text": "foo", "confidence": 0.9}')
    assert not res_extra_keys.valid
    assert "expected exactly one key ['text']" in (res_extra_keys.error_message or "")

    # Case 5: Violation - Non-JSON plain text response
    res_not_json = suite.validate_text_output("I entered John Doe in the field.")
    assert not res_not_json.valid
    assert "Output is not valid JSON" in (res_not_json.error_message or "")

    # Case 6: Violation - Invalid data type (number instead of string/null)
    res_bad_type = suite.validate_text_output('{"text": 12345}')
    assert not res_bad_type.valid
    assert "Value for 'text' must be string or null" in (res_bad_type.error_message or "")
