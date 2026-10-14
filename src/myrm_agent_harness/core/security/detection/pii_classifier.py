"""PII classifier — input-side personal information detection.

Classifies content into S1 (public) / S2 (sensitive) / S3 (confidential)
based on regex pattern matching for structured PII.

Detection strategy:
  1. The user's custom S3 keywords/patterns (custom_rules), on a text of any length
  2. Fast path: short messages bypass the built-in detectors
  3. Built-in S3 patterns, card numbers a card keyword introduces, passwords and credentials (short-circuit on
     confidential)
  4. The user's custom S2 keywords/patterns
  5. Built-in S2 patterns (personal information)
  6. Tool parameter & path checking

Detection functions are pure — no logging, no side effects, no state. The pattern tables and validators they
consult live in pii_patterns.

[INPUT]
- core.security.detection.card_context::find_card_number_spans (POS: Keyword-anchored detector for card numbers outside the network prefix table or with a typo in them.)
- core.security.detection.custom_rules::custom_rules, first_custom_span (POS: Single definition of custom-term matching for the privacy policy: the PII classifier, the redactor and the pseudonymizer share it, so detection and masking never disagree about what a user's keyword or pattern covers.)
- core.security.detection.password_heuristic::find_password_spans (POS: last-resort keyword-anchored detector for passwords without vendor prefix or entropy.)
- core.security.detection.pii_patterns::S2_PATTERNS, S3_PATTERNS, is_confirmed, is_placeholder (POS: Single definition of the built-in PII patterns and their validators: classification, redaction and pseudonymization all read it, so they never disagree about what a hit is.)

[OUTPUT]
- PIIClassification: detection result (level, matched patterns, confidence)
- classify_content(): classify text content
- contains_level(): whether a text holds content of one level, whatever else it holds at a higher one
- classify_tool_params(): classify tool call parameters
- classify_tool_result(): classify tool execution result

[POS]
Input-side PII classification engine. Runs the built-in patterns (bilingual CN/EN, in pii_patterns) with short-circuit optimization for efficient content scanning.

"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.detection.card_context import find_card_number_spans
from myrm_agent_harness.core.security.detection.custom_rules import custom_rules, first_custom_span
from myrm_agent_harness.core.security.detection.password_heuristic import find_password_spans
from myrm_agent_harness.core.security.detection.pii_patterns import (
    S2_PATTERNS,
    S3_PATTERNS,
    is_confirmed,
    is_placeholder,
)
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

# Pattern names of a detected password and card number: located by spans (password_heuristic, card_context), not by a
# regex in the pii_patterns tables.
PASSWORD_PATTERN = "password_context"
CARD_CONTEXT_PATTERN = "bank_card_context"

# ---------------------------------------------------------------------------
# Fast path thresholds
# ---------------------------------------------------------------------------

_MIN_CONTENT_LENGTH = 6
_FAST_PATH_ASCII_LENGTH = 20
# A custom pattern is named in the result by its first characters.
_PATTERN_NAME_LENGTH = 50

# ---------------------------------------------------------------------------
# Sensitive file paths (for tool parameter checking)
# ---------------------------------------------------------------------------

_DEFAULT_SENSITIVE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".env",
        ".env.local",
        ".env.production",
    }
)

_DEFAULT_SENSITIVE_NAMES: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "known_hosts",
        "authorized_keys",
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
    }
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class PIIClassification:
    """Result of PII classification."""

    level: SensitivityLevel
    patterns: list[str] = field(default_factory=list)
    confidence: float = 1.0


def _custom_hit(content: str, policy: PrivacyPolicy, level: SensitivityLevel) -> str | None:
    """Pattern name of the first custom keyword or pattern of *level* that *content* contains, if any."""
    span = first_custom_span(content, custom_rules(policy, level))
    if span is None:
        return None
    rule = span.rule if span.kind == "keyword" else span.rule[:_PATTERN_NAME_LENGTH]
    return f"custom_{level.value}_{span.kind}:{rule}"


def _built_in_s3(content: str) -> PIIClassification | None:
    """The S3 classification of confidential data the built-in detectors recognise, or None."""
    for name, pat in S3_PATTERNS:
        if any(is_confirmed(name, m.group(0)) for m in pat.finditer(content)):
            return PIIClassification(level=SensitivityLevel.S3, patterns=[name])

    # Card numbers outside the prefix table, or with a typo, that the text introduces as a card.
    if find_card_number_spans(content):
        return PIIClassification(level=SensitivityLevel.S3, patterns=[CARD_CONTEXT_PATTERN])

    # Passwords: the same keyword-anchored definition the persistence scan uses, in recall mode.
    if find_password_spans(content, strict=False):
        return PIIClassification(level=SensitivityLevel.S3, patterns=[PASSWORD_PATTERN])

    # Credentials: delegated to the leak detector.
    from myrm_agent_harness.core.security.detection.leak_detector import scan_for_leaks

    leak_matches = scan_for_leaks(content)
    if leak_matches:
        return PIIClassification(level=SensitivityLevel.S3, patterns=[f"credential:{m}" for m in leak_matches])
    return None


def _built_in_s2(content: str) -> PIIClassification | None:
    """The S2 classification of personal information the built-in detectors recognise, or None."""
    # ASCII short-text fast path skips only patterns that require CJK characters to
    # match (china_address). china_phone and china_courier match pure ASCII digit /
    # alphanumeric sequences ("13800138000", "SF1234567890123"), so skipping them on
    # short ASCII input silently misclassifies a bare phone or tracking number as S1.
    is_ascii_short = len(content) < _FAST_PATH_ASCII_LENGTH and content.isascii()
    check_patterns = S2_PATTERNS if not is_ascii_short else (p for p in S2_PATTERNS if p[0] != "china_address")
    for name, pat in check_patterns:
        for m in pat.finditer(content):
            if not is_placeholder(m.group(0)):
                return PIIClassification(level=SensitivityLevel.S2, patterns=[name])
    return None


def _classification_at(
    content: str, policy: PrivacyPolicy, level: SensitivityLevel, *, built_in: bool
) -> PIIClassification | None:
    """The *level* (S2 or S3) classification of *content*: the user's custom terms of that level, then the built-in
    detectors when *built_in*, or None when *content* holds nothing of that level."""
    if custom := _custom_hit(content, policy, level):
        return PIIClassification(level=level, patterns=[custom])
    if not built_in:
        return None
    return _built_in_s3(content) if level == SensitivityLevel.S3 else _built_in_s2(content)


def classify_content(content: str, policy: PrivacyPolicy) -> PIIClassification:
    """Classify text content into S1/S2/S3 based on PII detection.

    Pure function — no logging, no side effects. Short-circuits on S3. The user's own keywords and patterns apply to
    a text of any length; the built-in detectors skip texts shorter than ``_MIN_CONTENT_LENGTH``.
    """
    if not content or not policy.enabled:
        return PIIClassification(level=SensitivityLevel.S1)

    built_in = len(content) >= _MIN_CONTENT_LENGTH
    return (
        _classification_at(content, policy, SensitivityLevel.S3, built_in=built_in)
        or _classification_at(content, policy, SensitivityLevel.S2, built_in=built_in)
        or PIIClassification(level=SensitivityLevel.S1)
    )


def contains_level(content: str, policy: PrivacyPolicy, level: SensitivityLevel) -> bool:
    """Whether *content* holds something of *level* (S2 or S3), whatever else it holds at a higher one.

    ``classify_content`` names the highest level a text reaches; a message that reaches S3 may hold S2 content too.
    A disabled policy holds nothing, as it does for ``classify_content``.
    """
    if not policy.enabled or not content or level == SensitivityLevel.S1:
        return False
    return _classification_at(content, policy, level, built_in=len(content) >= _MIN_CONTENT_LENGTH) is not None


def classify_tool_params(tool_name: str, params: dict[str, object], policy: PrivacyPolicy) -> PIIClassification:
    """Classify tool call parameters for PII content.

    Checks:
    1. Tool name against sensitive tool lists
    2. Parameter values for PII content (reuses classify_content)
    3. File paths for sensitive extensions/names
    """
    if not policy.enabled:
        return PIIClassification(level=SensitivityLevel.S1)

    lower_name = tool_name.lower()

    # --- Check sensitive tools ---
    for tool in policy.sensitive_tools_s3:
        if tool.lower() in lower_name:
            return PIIClassification(level=SensitivityLevel.S3, patterns=[f"sensitive_tool_s3:{tool_name}"])
    for tool in policy.sensitive_tools_s2:
        if tool.lower() in lower_name:
            return PIIClassification(level=SensitivityLevel.S2, patterns=[f"sensitive_tool_s2:{tool_name}"])

    # --- Check file paths in parameters ---
    paths = _extract_paths(params)
    for path in paths:
        path_lower = path.lower()
        for ext in policy.sensitive_paths_s3:
            if path_lower.endswith(ext) or ext in path_lower:
                return PIIClassification(level=SensitivityLevel.S3, patterns=[f"sensitive_path:{path}"])
        for ext in _DEFAULT_SENSITIVE_EXTENSIONS:
            if path_lower.endswith(ext):
                return PIIClassification(level=SensitivityLevel.S3, patterns=[f"sensitive_file_ext:{ext}"])
        for name in _DEFAULT_SENSITIVE_NAMES:
            if name in path_lower:
                return PIIClassification(level=SensitivityLevel.S3, patterns=[f"sensitive_file_name:{name}"])

    # --- Check parameter values for PII ---
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        result = classify_content(value, policy)
        if result.level != SensitivityLevel.S1:
            return PIIClassification(level=result.level, patterns=[f"param:{key}:{p}" for p in result.patterns])

    return PIIClassification(level=SensitivityLevel.S1)


def classify_tool_result(content: str, tool_name: str, policy: PrivacyPolicy) -> PIIClassification:
    """Classify tool execution result for PII content.

    Delegates to classify_content with the same policy. The tool_name
    is used for logging context only.
    """
    return classify_content(content, policy)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PATH_KEYS: frozenset[str] = frozenset(
    {
        "path",
        "file",
        "filename",
        "filepath",
        "file_path",
        "source",
        "destination",
        "target",
        "input",
        "output",
    }
)


def _extract_paths(params: dict[str, object]) -> list[str]:
    """Extract file path values from tool parameters."""
    paths: list[str] = []
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        if key.lower() in _PATH_KEYS or (
            ("/" in value or "\\" in value) and len(value) < 500 and not value.startswith("http")
        ):
            paths.append(value)
    # Extract paths from command strings
    command = params.get("command") or params.get("code")
    if isinstance(command, str):
        paths.extend(_extract_paths_from_command(command))
    return paths


_COMMAND_PATH_RE = re.compile(r'(?:^|\s)([/~][^\s;|&<>"\']+)')


def _extract_paths_from_command(command: str) -> list[str]:
    """Extract file paths from shell command strings."""
    return [m.group(1) for m in _COMMAND_PATH_RE.finditer(command)]
