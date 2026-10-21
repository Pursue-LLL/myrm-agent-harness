"""Secret value rules: the one definition of a secret value versus a reference to one.

[INPUT]
- (none — pure regex patterns, no external dependencies)

[OUTPUT]
- Span / MIN_SECRET_VALUE_LENGTH / LABELLED_SECRET_MIN_LENGTH / STRONG_SYMBOLS / STRUCTURAL_SYMBOLS: vocabulary shared
  by the secret detectors.
- secret_value_span(): the secret inside the raw value span of a label or connector (trim, plausibility, references
  and already-redacted markers rejected, caller-chosen minimum length, letters-only and numeric values opt-in).
- is_reference_value(): True for a value that names a secret instead of being one (template, identifier, call,
  character class, the key itself, camel-case name).
- is_reference_token(): the same question for a free-standing high-entropy token (true when every piece between
  non-alphanumeric characters is a readable word or number: identifier, class name, constant, slug, domain, query string).
- mask_markdown_emphasis(): same-length copy of a text with markdown bold markers blanked, so markup is never read
  as secret characters.

[POS]
Shared by every path that decides whether text is a secret (keyword-anchored password heuristic, persistence
assignment spans, leak detector env/JSON credentials, entropy scan), so ``token = _active_value(...)`` or
``password=password`` is rejected identically everywhere instead of by whichever path happens to carry a rule for it.
"""

from __future__ import annotations

import re

Span = tuple[int, int]

MIN_SECRET_VALUE_LENGTH = 8
# A value the text itself assigns to a password label ("password: 123456") is a password at a shorter length.
LABELLED_SECRET_MIN_LENGTH = 6
_MAX_VALUE_LENGTH = 64
# Redaction markers ("[REDACTED]", "[REDACTED:env_credential]") already sit in text that is scanned again.
_REDACTION_MARKER_PREFIX = "[REDACTED"
# Masks ("********", "xxxxxxxx") repeat one or two characters.
_MIN_DISTINCT_CHARS = 3

# Strong symbols are password characters; structural ones only join segments ("xK9-mPq2-Lw8z") and also appear
# in prose, URLs and domains. "=" is deliberately absent: it separates a label from its value ("password=Zk9#..."),
# so the label must stay out.
STRONG_SYMBOLS = "@#$%^&*!?_"
STRUCTURAL_SYMBOLS = "-./+~"

# Markdown bold ("**Password**: x", "Password: **x**") is markup around the words, not part of the secret; a
# password that merely contains "**" inside ("Pa**ss12") keeps it.
_MARKDOWN_BOLD_RE = re.compile(r"(?<![A-Za-z0-9])\*{2,}|\*{2,}(?![A-Za-z0-9])")

_QUOTES = "\"'`“‘"
_CLOSING_BRACKETS = ")]}>"

# Code expressions and markup ("Optional[str]", "<jwt>", "[REDACTED]") and URLs are references, not secrets.
_CODE_CHARS_RE = re.compile(r"[()\[\]{}<>]")
# A name after a label: constant ("DB_PASSWORD", "_LOCAL_NO_AUTH_KEY_MARKER"), snake-case ("password_hash") or, unless
# the text quotes it, camel-case ("currentPassword"; a digit or symbol makes it a password, a quotation a literal).
_NAME_RE = re.compile(r"_*[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|_*[a-z]+(?:_[a-z]+)+")
_CAMEL_CASE_RE = re.compile(r"[a-z]{2,}(?:[A-Z][a-z]{2,})+")
_FIELD_STATE_WORDS = frozenset(
    {
        "required",
        "optional",
        "mandatory",
        "hidden",
        "masked",
        "redacted",
        "encrypted",
        "hashed",
        "unknown",
        "empty",
        "unset",
    }
)

# --- references to a secret -------------------------------------------------------------------------------------
# A template filled in at runtime, matched as a whole value: "$DB_PASSWORD", "${X}", "$(cmd)", "%(x)s", "%APPDATA%",
# "{x}", "<x>". "$" and "%" inside a value ("Pa$$w0rd2024", "Zk9%mango42") are password characters.
_TEMPLATE_RE = re.compile(
    r"\$[A-Z_][A-Z0-9_]*|\$[a-z_][a-z0-9_]*|\$\{[^{}]*\}|\$\([^()]*\)|%\([^()]*\)[sdrf]|%[A-Z_][A-Z0-9_]*%|\{[^{}]*\}|<[^<>]*>"
)
# An attribute chain ("settings.DB_PASSWORD", "apiKey?.trim", "status.HTTP_400_BAD_REQUEST"). A part is an
# identifier-short run of letters, or a constant with digits; a dotted password ("john.Smith2024") or credential
# ("<hex32>.<alnum16>") is neither. The two alternatives are disjoint (digits or none), so matching stays linear.
_CHAIN_PART = r"(?=[A-Z0-9_]*\d)[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Za-z_]{1,30}"
_ATTRIBUTE_CHAIN_RE = re.compile(rf"(?:{_CHAIN_PART})(?:\??\.(?:{_CHAIN_PART}))+")
# A TypeScript non-null assertion after a chain ("process.env.GROQ_API_KEY!"). It needs three parts: after two ("john.smith!")
# the "!" is as likely a password character as an assertion.
_NON_NULL_CHAIN_RE = re.compile(rf"(?:{_CHAIN_PART})(?:\??\.(?:{_CHAIN_PART})){{2,}}!")
# A call or subscript on a compound name ("_resolve_token(ctx)", "os.getenv(", "self._store.get["): what follows the
# opening bracket is arguments. Segments split at "_" and "." without overlap, so matching stays linear.
_CALL_RE = re.compile(r"_*[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z0-9]+|\??\._*[A-Za-z0-9]+)+[(\[]")
# Regular-expression fragments: adjacent character-class ranges ("a-zA-Z0-9_") and a quantified escape ("\s+").
# A lone escape or range is a legal password character sequence ("4iTHeH\Dp").
_CHAR_CLASS_RE = re.compile(r"(?:a-z|A-Z|0-9|a-f|A-F){2,}|\\[swdSWDb][+*?{]")
_KEY_SEPARATORS_RE = re.compile(r"[_\-\s]")
# What ends a value written as a call argument or collection item ("token=config.remote_token,").
_ARGUMENT_TERMINATORS = ",)]}"


def _fold(text: str) -> str:
    return _KEY_SEPARATORS_RE.sub("", text).lower()


def _is_bare_name(value: str, *, quoted: bool) -> bool:
    return bool(_NAME_RE.fullmatch(value) or (not quoted and _CAMEL_CASE_RE.fullmatch(value)))


def is_reference_value(value: str, *, key: str = "") -> bool:
    """Whether ``value`` names a secret instead of being one: a template, attribute chain (also with a TypeScript
    non-null ``!``), call, regex character class or the label itself (``password=password``, a pass-through argument;
    ``key`` is the label, when there is one).

    A bare constant or word is ambiguous in ``.env``-style text (``SECRET=my_long_secret_word``), so it counts as a
    reference only as a call argument (``secret=my_secret_word,``); ``secret_value_span`` rejects it after any label.
    """
    argument = value.rstrip(_ARGUMENT_TERMINATORS)
    return bool(
        _TEMPLATE_RE.fullmatch(value)
        or _ATTRIBUTE_CHAIN_RE.fullmatch(argument)
        or _NON_NULL_CHAIN_RE.fullmatch(argument)
        or _CALL_RE.match(value)
        or _CHAR_CLASS_RE.search(value)
        or (key and _fold(argument) == _fold(key))
        or (argument != value and _is_bare_name(argument, quoted=False))
    )


# --- references among free-standing tokens (entropy scan) --------------------------------------------------------
_KEYWORD_ARGUMENT_RE = re.compile(r"[A-Za-z_]\w*=")
_PIECE_SEPARATORS_RE = re.compile(r"[\W_]+")
# A readable piece is words (lower "length", Capitalised "Module", ACRONYM "HTTP"; an identifier word is short, a long
# letter run is random) with trailing digits (a year, a count), a number, a letter ("q"), or a version tag ("v2",
# "4o"). Every chunk ends where the next begins, so a piece has exactly one split and matching stays linear. Digits
# inside a word ("xK9mPq2") never read as a word: random credentials fail here.
_READABLE_PIECE_RE = re.compile(
    r"(?:[A-Z]?[a-z]{2,20}(?![a-z])|[A-Z]{2,12}(?:(?=[A-Z][a-z]{2,})|(?![A-Za-z])))+\d{0,8}"
    r"|\d{1,8}|[A-Za-z]\d{0,3}|\d{1,3}[A-Za-z]"
)


def is_reference_token(token: str, *, min_length: int) -> bool:
    """Whether a high-entropy-looking token is made only of readable words and numbers: an identifier, class name,
    constant, slug, domain, address or query string.

    A keyword argument (``max_tokens=...``) is judged by its value alone. The token is cut at every non-alphanumeric
    character; one random piece (a secret behind ``?token=`` or ``@``) makes the whole token a candidate again.
    """
    argument = _KEYWORD_ARGUMENT_RE.match(token)
    value = token[argument.end() :] if argument else token
    if len(value) < min_length:
        return True
    return all(_READABLE_PIECE_RE.fullmatch(piece) for piece in _PIECE_SEPARATORS_RE.split(value) if piece)


# --- value extraction --------------------------------------------------------------------------------------------
def mask_markdown_emphasis(text: str) -> str:
    """Blank out markdown bold markers, keeping every offset, so detection never takes markup for secret characters."""
    return _MARKDOWN_BOLD_RE.sub(lambda match: " " * len(match.group()), text)


def _is_secret_edge(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char in STRONG_SYMBOLS)


def _trim_secret_span(text: str, start: int, end: int) -> Span:
    """Shrink a span to start and end on a letter, digit or strong symbol (quotes and sentence punctuation drop out)."""
    while start < end and not _is_secret_edge(text[start]):
        start += 1
    while end > start and not _is_secret_edge(text[end - 1]):
        end -= 1
    return start, end


def _is_plausible_secret_value(value: str, *, allow_letters_only: bool, allow_numeric: bool, min_length: int) -> bool:
    if not min_length <= len(value) <= _MAX_VALUE_LENGTH:
        return False
    if _CODE_CHARS_RE.search(value) or "://" in value:
        return False
    if (value.isdigit() and not allow_numeric) or value.lower() in _FIELD_STATE_WORDS:
        return False
    # "111111" is a real password; "********" and "xxxxxxxx" are masks.
    if len(set(value)) < _MIN_DISTINCT_CHARS and not (allow_numeric and value.isdigit()):
        return False
    return allow_letters_only or any(char.isdigit() or char in STRONG_SYMBOLS for char in value)


def _template_closer(text: str, end: int) -> str:
    """The bracket right after a raw span that closes a template the span opened (``{name`` in ``{name}``), if the
    bracket ends the value; ``{abc}3&`` is a value that merely starts with braces."""
    bracket = text[end : end + 1]
    if not bracket or bracket not in _CLOSING_BRACKETS or _is_secret_edge(text[end + 1 : end + 2] or " "):
        return ""
    return bracket


def secret_value_span(
    text: str,
    start: int,
    end: int,
    *,
    allow_letters_only: bool,
    allow_numeric: bool = False,
    min_length: int = MIN_SECRET_VALUE_LENGTH,
    key: str = "",
) -> Span | None:
    """The secret inside the raw value span ``text[start:end]`` of a label or connector, or None.

    The raw span is trimmed (quotes and sentence punctuation drop out) and must then be plausible: not an existing
    redaction marker, not shorter than ``min_length``, purely numeric or a field-state word, and not a reference to a
    secret (template, identifier, call, code expression). A bracket right after the raw span closes a template the
    raw span only opened (``{name`` in ``{name}``). Letters-only values ("dragonfly") are ambiguous in prose
    ("required", "stored"), so they pass only where the caller knows the label names a password; so do purely
    numeric ones ("123456", ``allow_numeric``), which are otherwise years, counts and example values. ``key`` is the
    label the value is assigned to, when there is one.
    """
    if text.startswith(_REDACTION_MARKER_PREFIX, start):
        return None
    quoted = start > 0 and text[start - 1] in _QUOTES
    if is_reference_value(text[start:end] + _template_closer(text, end), key=key):
        return None
    start, end = _trim_secret_span(text, start, end)
    value = text[start:end]
    if is_reference_value(value, key=key) or _is_bare_name(value, quoted=quoted):
        return None
    if _is_plausible_secret_value(
        value, allow_letters_only=allow_letters_only, allow_numeric=allow_numeric, min_length=min_length
    ):
        return start, end
    return None
