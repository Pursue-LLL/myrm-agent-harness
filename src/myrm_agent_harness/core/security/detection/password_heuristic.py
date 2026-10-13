"""Password-like secret heuristic: unlabeled passwords and numeric PIN/OTP/2FA codes.

[INPUT]
- (none — pure regex patterns, no external dependencies)

[OUTPUT]
- looks_like_password(): the suspected secret token in a text, or None. Persistence redacts exactly the returned
  token, so it is the secret itself: the best-scored candidate (never the keyword or a neighbouring word),
  including generated passwords joined by "-./+~" and numeric credentials anchored to keywords.

[POS]
Last-resort detector for secrets that carry no vendor prefix and no high entropy (e.g. "Zk9#mango42"), which the
prefix/context/entropy detectors in leak_detector all miss. Conservative by construction, never a hard block.
"""

from __future__ import annotations

import re

# Detects standalone secrets (e.g. "Zk9#mango42") by requiring ALL THREE signals, keeping false positives low:
#   1. length in [6, 64]
#   2. mixed char classes (lower + upper or symbol)
#   3. a nearby "password" keyword or an assignment/declaration context
# Among the tokens that qualify, the one with the most character classes wins: a secret mixes more classes
# than the capitalised words around it.
_PASSWORD_KEYWORD_RE = re.compile(
    r"(?i)\b(?:password|passwd|passphrase|pwd|p@ssword|api secret|secret key|master password|"
    r"passcode|pass code|otp|2fa code|2fa|pin|verification code)\b|密码|口令|验证码"
)
# Strong symbols are password characters; structural ones only join segments ("xK9-mPq2-Lw8z") and also appear
# in prose, URLs and domains. "=" is deliberately absent: it separates a label from its value ("password=Zk9#..."),
# so the label must stay out.
_STRONG_SYMBOLS = "@#$%^&*!?_"
_STRUCTURAL_SYMBOLS = "-./+~"
_STRONG = re.escape(_STRONG_SYMBOLS)
_TOKEN_CHARS = rf"[A-Za-z0-9{_STRONG}{re.escape(_STRUCTURAL_SYMBOLS)}]"
# A token starts and ends on a letter, digit or strong symbol, so a trailing "!" belongs to the secret while a
# sentence-final "." does not. The class lookaheads stay inside the 64-char token window so scanning long
# unbroken runs (base64 blobs, paths) remains linear.
_PASSWORD_CANDIDATE_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?=[A-Za-z0-9{_STRONG}])"
    rf"(?={_TOKEN_CHARS}{{0,63}}[a-z])(?={_TOKEN_CHARS}{{0,63}}[A-Z{_STRONG}])"
    rf"{_TOKEN_CHARS}{{6,64}}(?<=[A-Za-z0-9{_STRONG}])(?![A-Za-z0-9])"
)
_PASSWORD_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:password|passwd|pwd|passphrase|密码|口令)\s*[:：=]\s*['\"]?[^\s'\";]+|['\"]password['\"]\s*:\s*['\"][^'\"]+['\"]"
)
# Numeric credentials (PIN/OTP/2FA/passcode) use a dedicated keyword group so
# a bare numeric token is only treated as a secret when it appears next to a
# numeric-credential keyword. "password: 1234567890" (example value) stays
# benign, while "the OTP code is 582013" is redacted.
_NUMERIC_CREDENTIAL_KEYWORD_RE = re.compile(
    r"(?i)\b(?:otp|2fa code|2fa|passcode|pass code|pin|verification code)\b|验证码|一次性密码"
)
_NUMERIC_CREDENTIAL_RE = re.compile(r"\b\d{4,12}\b")
# Year (19xx/20xx) and CN-mobile (1[3-9]\d{9}) tokens are the common
# false positives when they share a window with a numeric-credential
# keyword ("2FA enabled since 2024", "phone 13800138000 ... OTP") —
# redacting them would corrupt the stored memory.
_YEAR_TOKEN_RE = re.compile(r"(?:19|20)\d{2}")
_CN_MOBILE_TOKEN_RE = re.compile(r"1[3-9]\d{9}")
# Maximum distance (chars) between a numeric-credential keyword and its code.
_NUMERIC_CREDENTIAL_WINDOW = 60
# Fallback window *before* the keyword. Tighter than the after-window so a
# stray number that merely precedes the keyword (e.g. a phone number) is not
# mistaken for the code when no code follows it.
_NUMERIC_CREDENTIAL_BEFORE_WINDOW = 20


def _is_password_candidate(token: str) -> bool:
    """Reject the keyword itself and hyphen/dot/slash-joined prose (product names, domains, paths).

    A token joined by structural symbols is a secret only when it also carries a digit or a strong
    symbol: "Password-Manager" and "example.com/Reset" are words, "xK9-mPq2-Lw8z" is generated.
    """
    if _PASSWORD_KEYWORD_RE.fullmatch(token):
        return False
    if any(char in _STRUCTURAL_SYMBOLS for char in token):
        return any(char.isdigit() or char in _STRONG_SYMBOLS for char in token)
    return True


def _char_class_count(token: str) -> int:
    """Number of distinct classes among lowercase, uppercase, digit and strong symbol.

    Structural symbols do not count: a hyphenated network name must not outrank the password next to it.
    """
    return sum(
        (
            any(char.islower() for char in token),
            any(char.isupper() for char in token),
            any(char.isdigit() for char in token),
            any(char in _STRONG_SYMBOLS for char in token),
        )
    )


def _find_password_token(text: str) -> str | None:
    """Best-scored password candidate; the earliest wins ties."""
    candidates = [
        token for match in _PASSWORD_CANDIDATE_RE.finditer(text) if _is_password_candidate(token := match.group(0))
    ]
    return max(candidates, key=_char_class_count, default=None)


def _find_numeric_credential(text: str) -> str | None:
    """Return the 4-12 digit token anchored to a numeric-credential keyword.

    Scans the whole text (so token boundaries are never truncated), preferring
    a token after the keyword, then before it, both within a tight window.
    Year/CN-mobile shaped tokens are skipped: they are far more likely to be
    dates/contacts than PINs, and redacting them would corrupt the memory.
    """
    kw = _NUMERIC_CREDENTIAL_KEYWORD_RE.search(text)
    if kw is None:
        return None

    def _is_ignored(token: str) -> bool:
        return bool(_YEAR_TOKEN_RE.fullmatch(token) or _CN_MOBILE_TOKEN_RE.fullmatch(token))

    def _first_in(lo: int, hi: int) -> str | None:
        for match in _NUMERIC_CREDENTIAL_RE.finditer(text):
            if lo <= match.start() and match.end() <= hi and not _is_ignored(match.group(0)):
                return match.group(0)
        return None

    after = _first_in(kw.end(), kw.end() + _NUMERIC_CREDENTIAL_WINDOW)
    if after is not None:
        return after
    return _first_in(max(0, kw.start() - _NUMERIC_CREDENTIAL_BEFORE_WINDOW), kw.start())


def looks_like_password(text: str) -> str | None:
    """Return the suspected password token, or None.

    Conservative heuristic requiring length + char-class mix + keyword or
    assignment context. Never called on blank input.
    """
    if not text:
        return None

    if not (_PASSWORD_KEYWORD_RE.search(text) or _PASSWORD_ASSIGNMENT_RE.search(text)):
        return None

    return _find_password_token(text) or _find_numeric_credential(text)
