"""Agent response locale and formality suffix (append to user_instructions tail).

[INPUT]
- (none — leaf module)

[OUTPUT]
- parse_response_locale_policy: read policy from engine_params
- build_response_locale_suffix: stable instruction block for LLM output register

[POS]
Harness SSOT for Korean honorific / locale output policy. Server appends the suffix to
user_instructions (not system_prompt prefix) to preserve prompt cache on the system block.
"""

from __future__ import annotations

from typing import Any, Final, Literal, TypedDict

FormalityLevel = Literal["formal-polite", "casual"]

_KO_FORMAL_SUFFIX: Final[str] = (
    "\n\n**Response language (Korean)**\n"
    "Write all user-facing replies in Korean.\n"
    "Use formal polite speech (합니다/하십시오체). Address the user respectfully.\n"
    "Keep product names, code, paths, and URLs unchanged."
)

_KO_CASUAL_SUFFIX: Final[str] = (
    "\n\n**Response language (Korean)**\n"
    "Write all user-facing replies in Korean.\n"
    "Use a natural conversational tone while staying professional.\n"
    "Keep product names, code, paths, and URLs unchanged."
)


class ResponseLocalePolicy(TypedDict):
    locale: str
    formality: FormalityLevel


def parse_response_locale_policy(
    engine_params: dict[str, Any] | None,
) -> ResponseLocalePolicy | None:
    """Return normalized policy when engine_params contains response_locale_policy."""
    if not engine_params:
        return None
    raw = engine_params.get("response_locale_policy")
    if not isinstance(raw, dict):
        return None
    locale = str(raw.get("locale") or "").strip()
    if not locale:
        return None
    formality_raw = str(raw.get("formality") or "formal-polite").strip().lower()
    formality: FormalityLevel = "casual" if formality_raw == "casual" else "formal-polite"
    return ResponseLocalePolicy(locale=locale, formality=formality)


def build_response_locale_suffix(
    engine_params: dict[str, Any] | None,
) -> str:
    """Build a stable suffix block from agent engine_params.response_locale_policy."""
    policy = parse_response_locale_policy(engine_params)
    if policy is None:
        return ""
    locale = policy["locale"].lower()
    if not locale.startswith("ko"):
        return ""
    if policy["formality"] == "casual":
        return _KO_CASUAL_SUFFIX
    return _KO_FORMAL_SUFFIX
