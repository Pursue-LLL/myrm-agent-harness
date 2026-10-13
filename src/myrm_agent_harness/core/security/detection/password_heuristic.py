"""Password-like secret heuristic: keyword-anchored passwords and numeric PIN/OTP/2FA codes.

[INPUT]
- core.security.detection.secret_value (POS: shared value rules, reference rejection, markup masking.)

[OUTPUT]
- find_password_spans(): sorted (start, end) spans of the secrets that sit next to a credential keyword. A span is the
  secret itself, never the keyword or a neighbouring word; texts without a keyword yield nothing.
  Only keyword anchoring lives here: what counts as a secret value (trim, plausibility, references) is decided by
  secret_value.py, shared with persistence assignment spans and the leak detector.

[POS]
Last-resort detector for secrets that carry no vendor prefix and no high entropy (e.g. "Zk9#mango42"), which the
prefix/context/entropy detectors in leak_detector all miss. Every secret is anchored to a keyword occurrence, so a
password keyword somewhere in a long document never turns ordinary words elsewhere into secrets. Conservative by
construction, never a hard block.
"""

from __future__ import annotations

import re
from bisect import bisect_left

from myrm_agent_harness.core.security.detection.secret_value import (
    STRONG_SYMBOLS,
    STRUCTURAL_SYMBOLS,
    Span,
    is_reference_value,
    mask_markdown_emphasis,
    secret_value_span,
)

# "pin" is an everyday verb ("pin the message", "pin to v2"). As a credential it is the acronym "PIN" or is introduced
# explicitly or followed directly by the code ("my pin is 4821", "pin: 4821", "my atm pin 4821").
_PIN_KEYWORD = r"(?-i:PIN)|pin(?=\s*(?:code|number)?\s*(?:(?:is|was)\b|[:=：]|是|为|\d))"
_PASSWORD_KEYWORD_RE = re.compile(
    r"\b(?:password|passwd|passphrase|pwd|p@ssword|api secret|secret key|master password|"
    rf"passcode|pass code|otp|2fa code|2fa|{_PIN_KEYWORD}|verification code)\b|密码|口令|验证码",
    re.IGNORECASE,
)

_STRONG = re.escape(STRONG_SYMBOLS)
_TOKEN_CHARS = rf"[A-Za-z0-9{_STRONG}{re.escape(STRUCTURAL_SYMBOLS)}]"
# A token starts and ends on a letter, digit or strong symbol, so a trailing "!" belongs to the secret while a
# sentence-final "." does not. The class lookaheads stay inside the 64-char token window so scanning long
# unbroken runs (base64 blobs, paths) remains linear.
_PASSWORD_CANDIDATE_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?=[A-Za-z0-9{_STRONG}])"
    rf"(?={_TOKEN_CHARS}{{0,63}}[a-z])(?={_TOKEN_CHARS}{{0,63}}[A-Z{_STRONG}])"
    rf"{_TOKEN_CHARS}{{6,64}}(?<=[A-Za-z0-9{_STRONG}])(?![A-Za-z0-9])"
)
# A token that merely sits near a keyword must look generated (four classes: lower, upper, digit, strong symbol);
# "iPhone15Pro" or a capitalised word does not. A token the text introduces explicitly ("is", ":", "=", "是") only has
# to pass secret_value_span.
_MIN_UNANCHORED_CLASSES = 4
_TOKEN_WINDOW_BEFORE = 32
_TOKEN_WINDOW_AFTER = 80

# keyword + filler ("for MyHome-5G") + connector + value. The filler never crosses a sentence end or a label
# delimiter, so the first connector after the keyword introduces its value.
_VALUE_CHAR = r"(?![,;\"'`])[\x21-\x7e]"
_VALUE_AFTER_CONNECTOR_RE = re.compile(
    r"[^\n.!?:=。！？：]{0,40}?(?:\b(?:is|was|are|to)\b|[:=：]|是|为|改成|改为|设为)\s*[\"'“‘`]?"
    rf"(?P<value>{_VALUE_CHAR}+)",
    re.IGNORECASE,
)

# Numeric credentials (PIN/OTP/2FA/passcode) use a dedicated keyword group so a bare numeric token is only treated
# as a secret when it appears next to a numeric-credential keyword. "password: 1234567890" (example value) stays
# benign, while "the OTP code is 582013" is redacted.
_NUMERIC_CREDENTIAL_KEYWORD_RE = re.compile(
    rf"\b(?:otp|2fa code|2fa|passcode|pass code|{_PIN_KEYWORD}|verification code)\b|验证码|一次性密码",
    re.IGNORECASE,
)
# "#6716" is an issue or pull request reference, never a code.
_NUMERIC_CREDENTIAL_RE = re.compile(r"(?<!#)\b\d{4,12}\b")
# Year (19xx/20xx) and CN-mobile (1[3-9]\d{9}) tokens are the common false positives when they share a window with a
# numeric-credential keyword ("2FA enabled since 2024", "phone 13800138000 ... OTP") — redacting them would corrupt
# the stored memory.
_YEAR_TOKEN_RE = re.compile(r"(?:19|20)\d{2}")
_CN_MOBILE_TOKEN_RE = re.compile(r"1[3-9]\d{9}")
# Maximum distance (chars) between a numeric-credential keyword and its code.
_NUMERIC_CREDENTIAL_WINDOW = 60
# Fallback window *before* the keyword. Tighter than the after-window so a stray number that merely precedes the
# keyword (e.g. a phone number) is not mistaken for the code when no code follows it.
_NUMERIC_CREDENTIAL_BEFORE_WINDOW = 20
# A code written before its label ("582013 is my OTP", "use 582013 as the OTP") shares a clause with it; any
# punctuation in between ("(RFC 6238): 2FA", "#1622: pin") means the number belongs to something else.
_SAME_CLAUSE_RE = re.compile(r"[\w\s'’-]*")


def _char_class_count(token: str) -> int:
    """Number of distinct classes among lowercase, uppercase, digit and strong symbol.

    Structural symbols do not count: a hyphenated network name must not outrank the password next to it.
    """
    return sum(
        (
            any(char.islower() for char in token),
            any(char.isupper() for char in token),
            any(char.isdigit() for char in token),
            any(char in STRONG_SYMBOLS for char in token),
        )
    )


def _is_generated_token(token: str) -> bool:
    """Reject the keyword itself, references to a secret and hyphen/dot/slash-joined prose.

    References are names and patterns (``status.HTTP_400_BAD_REQUEST``, ``a-zA-Z0-9_``); prose is product names,
    domains and paths. A token joined by structural symbols is a secret only when it also carries a digit or a strong
    symbol: "Password-Manager" and "example.com/Reset" are words, "xK9-mPq2-Lw8z" is generated.
    """
    if _PASSWORD_KEYWORD_RE.fullmatch(token) or is_reference_value(token):
        return False
    if any(char in STRUCTURAL_SYMBOLS for char in token) and not any(
        char.isdigit() or char in STRONG_SYMBOLS for char in token
    ):
        return False
    return _char_class_count(token) >= _MIN_UNANCHORED_CLASSES


def _value_after_connector(text: str, keyword: re.Match[str]) -> Span | None:
    match = _VALUE_AFTER_CONNECTOR_RE.match(text, keyword.end())
    if match is None:
        return None
    return secret_value_span(text, match.start("value"), match.end("value"), allow_letters_only=False)


def _generated_tokens(text: str) -> list[Span]:
    return [match.span() for match in _PASSWORD_CANDIDATE_RE.finditer(text) if _is_generated_token(match.group(0))]


def _best_token_near(text: str, keyword: re.Match[str], tokens: list[Span]) -> Span | None:
    """The most generated-looking token around the keyword; the earliest wins ties."""
    low = keyword.start() - _TOKEN_WINDOW_BEFORE
    high = keyword.end() + _TOKEN_WINDOW_AFTER
    nearby: list[Span] = []
    index = bisect_left(tokens, (low, 0))
    while index < len(tokens) and tokens[index][0] < high:
        nearby.append(tokens[index])
        index += 1
    return max(nearby, key=lambda span: _char_class_count(text[span[0] : span[1]]), default=None)


def _numeric_credentials(text: str) -> list[Span]:
    return [
        match.span()
        for match in _NUMERIC_CREDENTIAL_RE.finditer(text)
        if not (_YEAR_TOKEN_RE.fullmatch(match.group(0)) or _CN_MOBILE_TOKEN_RE.fullmatch(match.group(0)))
    ]


def _first_within(numbers: list[Span], low: int, high: int) -> Span | None:
    index = bisect_left(numbers, (low, 0))
    while index < len(numbers) and numbers[index][0] < high:
        if numbers[index][1] <= high:
            return numbers[index]
        index += 1
    return None


def _number_before(numbers: list[Span], text: str, keyword: re.Match[str]) -> Span | None:
    span = _first_within(numbers, max(0, keyword.start() - _NUMERIC_CREDENTIAL_BEFORE_WINDOW), keyword.start())
    if span is not None and _SAME_CLAUSE_RE.fullmatch(text, span[1], keyword.start()):
        return span
    return None


def find_password_spans(text: str) -> list[Span]:
    """Spans of the secrets anchored to a credential keyword, in text order without duplicates.

    Per keyword occurrence the first rule that finds a value wins: a value the text introduces ("password is X",
    "密码：X"), else a generated-looking token nearby. Numeric PIN/OTP/2FA codes are anchored separately, preferring a
    code after the keyword within a tight window, then one just before it in the same clause.
    """
    if not text:
        return []

    text = mask_markdown_emphasis(text)
    spans: set[Span] = set()
    tokens: list[Span] | None = None
    for keyword in _PASSWORD_KEYWORD_RE.finditer(text):
        span = _value_after_connector(text, keyword)
        if span is None:
            if tokens is None:
                tokens = _generated_tokens(text)
            span = _best_token_near(text, keyword, tokens)
        if span is not None:
            spans.add(span)

    numbers: list[Span] | None = None
    for keyword in _NUMERIC_CREDENTIAL_KEYWORD_RE.finditer(text):
        if numbers is None:
            numbers = _numeric_credentials(text)
        span = _first_within(numbers, keyword.end(), keyword.end() + _NUMERIC_CREDENTIAL_WINDOW) or _number_before(
            numbers, text, keyword
        )
        if span is not None:
            spans.add(span)
    return sorted(spans)
