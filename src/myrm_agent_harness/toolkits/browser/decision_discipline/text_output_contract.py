# [INPUT]: TextOutputContractResult
# [OUTPUT]: BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT, parse_and_validate_text_contract
# [POS]: toolkits/browser/decision_discipline/text_output_contract.py

"""Browser text generation output contract enforcing single-key JSON structure.

[INPUT]
- TextOutputContractResult: Verification contract from decision_discipline_types.

[OUTPUT]
- BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT: Prompt specifying single-key text contract.
- parse_and_validate_text_contract: Deterministic parser validating exact {"text": string|null} schema.

[POS]
Output contract engine preventing formatting drift, hallucinations, and conversational chatter.
"""

from __future__ import annotations

import json
import re

from .decision_discipline_types import TextOutputContractResult

BROWSER_TEXT_OUTPUT_CONTRACT_PROMPT: str = (
    "Return a JSON object with exactly one key, text: the exact string to enter in the selected field.\n"
    "Infer the value from the original goal and field meaning, using current page context and history.\n"
    "No commentary, code, or browser actions. Never invent personal information.\n"
    'If a required value is missing, return {"text": null}. Otherwise return {"text": "the field value"}.'
)

JSON_CODEBLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_and_validate_text_contract(raw_response: str) -> TextOutputContractResult:
    """Parse and validate LLM output against the strict single-key text generation contract.

    Invariants:
    1. Must be a valid JSON object.
    2. Must contain exactly one key: 'text'.
    3. Value of 'text' must be either string or null (None).
    4. Must not contain extra keys, comments, conversational chatter, or executable scripts.
    """
    cleaned = raw_response.strip()

    # Unwrap markdown fenced json block if present
    block_match = JSON_CODEBLOCK_PATTERN.search(cleaned)
    if block_match:
        cleaned = block_match.group(1).strip()

    try:
        data = json.loads(cleaned)
    except Exception as e:
        return TextOutputContractResult(
            valid=False,
            extracted_text=None,
            is_null=False,
            error_message=f"Output is not valid JSON: {e}",
        )

    if not isinstance(data, dict):
        return TextOutputContractResult(
            valid=False,
            extracted_text=None,
            is_null=False,
            error_message=f"Expected JSON object, got {type(data).__name__}",
        )

    keys = list(data.keys())
    if keys != ["text"]:
        return TextOutputContractResult(
            valid=False,
            extracted_text=None,
            is_null=False,
            error_message=(
                f"Contract violation: expected exactly one key ['text'], found {keys}. "
                "No extraneous keys or commentary permitted."
            ),
        )

    val = data["text"]
    if val is None:
        return TextOutputContractResult(
            valid=True,
            extracted_text=None,
            is_null=True,
            error_message=None,
        )

    if not isinstance(val, str):
        return TextOutputContractResult(
            valid=False,
            extracted_text=None,
            is_null=False,
            error_message=f"Value for 'text' must be string or null, got {type(val).__name__}",
        )

    return TextOutputContractResult(
        valid=True,
        extracted_text=val,
        is_null=False,
        error_message=None,
    )
