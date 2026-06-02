"""PII classifier — input-side personal information detection.

Classifies content into S1 (public) / S2 (sensitive) / S3 (confidential)
based on regex pattern matching for structured PII.

Detection strategy:
  1. Fast path: short messages bypass expensive checks
  2. S3 patterns first (short-circuit on confidential)
  3. S2 patterns (personal information)
  4. Credential delegation to leak_detector (S3)
  5. Custom user-defined keywords/patterns
  6. Tool parameter & path checking

All patterns are pre-compiled module-level constants. Detection functions
are pure — no logging, no side effects, no state.

[INPUT]

[OUTPUT]
- PIIClassification: detection result (level, matched patterns, confidence)
- classify_content(): classify text content
- classify_tool_params(): classify tool call parameters
- classify_tool_result(): classify tool execution result

[POS]
Input-side PII classification engine. 30+ built-in regex patterns (bilingual CN/EN) with short-circuit optimization for efficient content scanning.

"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

# ---------------------------------------------------------------------------
# Fast path thresholds
# ---------------------------------------------------------------------------

_MIN_CONTENT_LENGTH = 6
_FAST_PATH_ASCII_LENGTH = 20

# ---------------------------------------------------------------------------
# S3 patterns — confidential (identity documents, financial accounts)
# ---------------------------------------------------------------------------

_CHINA_ID_RE = re.compile(
    r"(?<!\d)"
    r"[1-9]\d{5}"
    r"(?:19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])"
    r"\d{3}[\dXx]"
    r"(?!\d)"
)

_BANK_CARD_RE = re.compile(
    r"(?<!\d)"
    r"(?:62|4\d|5[1-5]|3[47])\d{13,17}"
    r"(?!\d)"
)

_PASSWORD_CONTEXT_RE = re.compile(
    r"(?:password|passwd|pwd|pass|密码|口令)"
    r"\s*[:=]\s*"
    r"['\"]?(\S{6,})['\"]?",
    re.IGNORECASE,
)

_CHINA_PASSPORT_RE = re.compile(
    r"(?<![A-Za-z])"
    r"[EeGg]\d{8}"
    r"(?![A-Za-z\d])"
)

_S3_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("china_id_card", _CHINA_ID_RE),
    ("bank_card", _BANK_CARD_RE),
    ("password_context", _PASSWORD_CONTEXT_RE),
    ("china_passport", _CHINA_PASSPORT_RE),
)

# ---------------------------------------------------------------------------
# S2 patterns — sensitive (personal contact, location)
# ---------------------------------------------------------------------------

_CHINA_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?86[-\s]?)?"
    r"1[3-9]\d{9}"
    r"(?!\d)"
)

_INTL_PHONE_RE = re.compile(r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_CREDIT_CARD_VISIBLE_RE = re.compile(
    r"(?<!\d)"
    r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}"
    r"(?!\d)"
)

_PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)

_CHINA_ADDRESS_RE = re.compile(
    r"(?:"
    r"(?:北京|上海|天津|重庆|[^\s]{2,4}(?:省|自治区))"
    r".{0,6}(?:市|区|县|镇|乡|街道|路|号|弄|栋|楼|室|单元)"
    r"|"
    r"(?:市|区|县).{0,10}(?:路|街|道|巷|弄).{0,6}(?:号|栋|楼|室)"
    r")"
)

_CHINA_COURIER_RE = re.compile(
    r"(?:SF|YT|YD|ZT|EMS|YZPY|JD|DBL|YUNDA|STO|ZTO|BEST)"
    r"\d{10,15}",
    re.IGNORECASE,
)

_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

_S2_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("china_phone", _CHINA_PHONE_RE),
    ("intl_phone", _INTL_PHONE_RE),
    ("email", _EMAIL_RE),
    ("credit_card_visible", _CREDIT_CARD_VISIBLE_RE),
    ("private_ip", _PRIVATE_IP_RE),
    ("china_address", _CHINA_ADDRESS_RE),
    ("china_courier", _CHINA_COURIER_RE),
    ("us_ssn", _SSN_RE),
)

# ---------------------------------------------------------------------------
# Placeholder exclusion (reuse logic from leak_detector)
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-].*|xxx+|placeholder|example|changeme|TODO|CHANGE_ME|INSERT_HERE|"
    r"<[^>]+>|\$\{[^}]+\}|%\([^)]+\)s|None|null|undefined|test|demo|fake|dummy|sample"
    r"|user@example\.com|john@doe\.com|test@test\.com|admin@admin\.com"
    r"|12345678901|00000000000|11111111111"
    r")$",
    re.IGNORECASE,
)

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
# Custom keyword matching (word-boundary aware)
# ---------------------------------------------------------------------------


def _keyword_matches(text: str, keyword: str) -> bool:
    """Check if keyword appears in text at word-like boundaries.

    For keywords starting with "." (file extensions), only check that
    the tail is not followed by an alphanumeric char.
    """
    lower_text = text.lower()
    lower_kw = keyword.lower()
    if lower_kw not in lower_text:
        return False
    idx = lower_text.find(lower_kw)
    if keyword.startswith("."):
        end = idx + len(lower_kw)
        return end >= len(lower_text) or not lower_text[end].isalnum()
    if idx > 0 and lower_text[idx - 1].isalnum():
        return False
    end = idx + len(lower_kw)
    return not (end < len(lower_text) and lower_text[end].isalnum())


# ---------------------------------------------------------------------------
# Luhn checksum (bank card / credit card validation)
# ---------------------------------------------------------------------------


def _luhn_valid(digits: str) -> bool:
    """Validate a digit string against the Luhn algorithm."""
    if not digits.isdigit() or len(digits) < 13:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# ID card checksum (China 18-digit)
# ---------------------------------------------------------------------------

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"


def _china_id_valid(id_str: str) -> bool:
    """Validate China 18-digit ID card number with checksum."""
    if len(id_str) != 18:
        return False
    body = id_str[:17]
    if not body.isdigit():
        return False
    total = sum(int(body[i]) * _ID_WEIGHTS[i] for i in range(17))
    expected = _ID_CHECK_CODES[total % 11]
    return id_str[17].upper() == expected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class PIIClassification:
    """Result of PII classification."""

    level: SensitivityLevel
    patterns: list[str] = field(default_factory=list)
    confidence: float = 1.0


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value.strip()))


def classify_content(content: str, policy: PrivacyPolicy) -> PIIClassification:
    """Classify text content into S1/S2/S3 based on PII detection.

    Pure function — no logging, no side effects. Short-circuits on S3.
    """
    if not content or not policy.enabled:
        return PIIClassification(level=SensitivityLevel.S1)

    if len(content) < _MIN_CONTENT_LENGTH:
        return PIIClassification(level=SensitivityLevel.S1)

    patterns: list[str] = []
    level = SensitivityLevel.S1

    # --- S3 custom keywords (highest priority) ---
    for kw in policy.custom_keywords_s3:
        if _keyword_matches(content, kw):
            return PIIClassification(level=SensitivityLevel.S3, patterns=[f"custom_s3_keyword:{kw}"])

    # --- S3 custom patterns ---
    for pat_str in policy.custom_patterns_s3:
        try:
            if re.search(pat_str, content, re.IGNORECASE):
                return PIIClassification(level=SensitivityLevel.S3, patterns=[f"custom_s3_pattern:{pat_str[:50]}"])
        except re.error:
            pass

    # --- S3 built-in patterns ---
    for name, pat in _S3_PATTERNS:
        for m in pat.finditer(content):
            val = m.group(0)
            if _is_placeholder(val):
                continue
            if name == "china_id_card" and not _china_id_valid(val):
                continue
            if name == "bank_card" and not _luhn_valid(val.replace("-", "").replace(" ", "")):
                continue
            return PIIClassification(level=SensitivityLevel.S3, patterns=[name])

    # --- S3 via credential detection (delegate to leak_detector) ---
    from myrm_agent_harness.core.security.detection.leak_detector import scan_for_leaks

    leak_matches = scan_for_leaks(content)
    if leak_matches:
        return PIIClassification(level=SensitivityLevel.S3, patterns=[f"credential:{m}" for m in leak_matches])

    # --- S2 custom keywords ---
    for kw in policy.custom_keywords_s2:
        if _keyword_matches(content, kw):
            patterns.append(f"custom_s2_keyword:{kw}")
            level = SensitivityLevel.S2

    # --- S2 custom patterns ---
    for pat_str in policy.custom_patterns_s2:
        try:
            if re.search(pat_str, content, re.IGNORECASE):
                patterns.append(f"custom_s2_pattern:{pat_str[:50]}")
                level = SensitivityLevel.S2
                break
        except re.error:
            pass

    # --- S2 built-in patterns ---
    if level == SensitivityLevel.S1:
        is_ascii_short = len(content) < _FAST_PATH_ASCII_LENGTH and content.isascii()
        check_patterns = (
            _S2_PATTERNS
            if not is_ascii_short
            else (p for p in _S2_PATTERNS if p[0] not in ("china_phone", "china_address", "china_courier"))
        )
        for name, pat in check_patterns:
            for m in pat.finditer(content):
                val = m.group(0)
                if _is_placeholder(val):
                    continue
                patterns.append(name)
                level = SensitivityLevel.S2
                break
            if level == SensitivityLevel.S2:
                break

    return PIIClassification(level=level, patterns=patterns)


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
        if not isinstance(value, str) or len(value) < _MIN_CONTENT_LENGTH:
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
        if key.lower() in _PATH_KEYS or (("/" in value or "\\" in value) and len(value) < 500 and not value.startswith("http")):
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
