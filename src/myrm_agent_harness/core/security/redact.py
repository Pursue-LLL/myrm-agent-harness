"""Regex-based secret redaction for tool output and logs.

Applies pattern matching to mask API keys, tokens, and credentials
before they reach the LLM context or log files. Acts as a second
defense layer complementing ``sanitize_env`` (source removal).

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- redact_sensitive_text(text) -> str — apply all redaction patterns
- escape_invisible_unicode(text) -> str — escape invisible chars to \\u{XXXX}
- redact_for_display(args) -> dict — recursive redaction for approval UI
- RedactingFormatter — logging.Formatter subclass for production logs

[POS]
Agent output redaction layer. Complements sanitize_env (source-level dangerous env var removal) with display-level sensitive text masking.

"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

_REDACT_ENABLED = True

# ── Bounded replace constants (防ReDoS) ──────────────────────────
_REDACT_REGEX_CHUNK_THRESHOLD = 32768  # 32KB
_REDACT_REGEX_CHUNK_SIZE = 16384  # 16KB
_CHUNK_OVERLAP = 4096  # covers RSA-4096 PEM (~3200 chars) + margin


def set_redact_enabled(enabled: bool) -> None:
    """Configure secret redaction at startup. Enabled by default."""
    global _REDACT_ENABLED
    _REDACT_ENABLED = enabled


def _replace_pattern_bounded(
    text: str,
    pattern: re.Pattern[str],
    replacer: str | Callable[[re.Match[str]], str],
    chunk_threshold: int = _REDACT_REGEX_CHUNK_THRESHOLD,
    chunk_size: int = _REDACT_REGEX_CHUNK_SIZE,
) -> str:
    """Replace pattern with bounded chunking to prevent ReDoS.

    Each chunk extends by ``_CHUNK_OVERLAP`` bytes into the next chunk
    so patterns spanning a boundary are matched intact.  Deduplication
    via ``seen_starts`` ensures overlap-region matches are not applied
    twice.  Results are assembled with a single forward join (O(n)).

    Args:
        text: Input text
        pattern: Compiled regex pattern
        replacer: Replacement string or callable
        chunk_threshold: Min text length to trigger chunking (default: 32KB)
        chunk_size: Size of each chunk (default: 16KB)

    Returns:
        Redacted text
    """
    if len(text) <= chunk_threshold:
        return pattern.sub(replacer, text)

    matches: list[tuple[int, int, str]] = []
    seen_starts: set[int] = set()

    pos = 0
    while pos < len(text):
        chunk_end = min(pos + chunk_size + _CHUNK_OVERLAP, len(text))
        chunk = text[pos:chunk_end]

        for m in pattern.finditer(chunk):
            abs_start = pos + m.start()
            if abs_start in seen_starts:
                continue
            seen_starts.add(abs_start)
            abs_end = pos + m.end()
            repl = replacer(m) if callable(replacer) else m.expand(replacer)
            matches.append((abs_start, abs_end, repl))

        pos += chunk_size

    if not matches:
        return text

    parts: list[str] = []
    last_end = 0
    for abs_start, abs_end, repl in matches:
        parts.append(text[last_end:abs_start])
        parts.append(repl)
        last_end = abs_end
    parts.append(text[last_end:])
    return "".join(parts)


def _redact_pem_block(block: str) -> str:
    """Redact PEM block while preserving header/footer for debugging.

    Example:
        Input:  -----BEGIN RSA PRIVATE KEY-----
                MIIEowIBAAKCAQEA...
                -----END RSA PRIVATE KEY-----
        Output: -----BEGIN RSA PRIVATE KEY-----
                ...redacted...
                -----END RSA PRIVATE KEY-----
    """
    lines = [line for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return "***"
    return f"{lines[0]}\n...redacted...\n{lines[-1]}"


# ── Structural patterns (token-structure detection) ──────────────

_PREFIX_PATTERNS: tuple[str, ...] = (
    r"sk-[A-Za-z0-9_-]{10,}",
    r"sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{10,}",  # Anthropic (OPT-4)
    r"ghp_[A-Za-z0-9]{10,}",
    r"github_pat_[A-Za-z0-9_]{10,}",
    r"gho_[A-Za-z0-9]{10,}",
    r"ghu_[A-Za-z0-9]{10,}",
    r"ghs_[A-Za-z0-9]{10,}",
    r"ghr_[A-Za-z0-9]{10,}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",  # Slack
    r"xapp-[A-Za-z0-9-]{10,}",  # Slack App (OPT-4)
    r"gsk_[A-Za-z0-9_-]{10,}",  # Groq (OPT-4)
    r"AIza[A-Za-z0-9_-]{30,}",
    r"AKIA[A-Z0-9]{16}",
    r"sk_live_[A-Za-z0-9]{10,}",
    r"sk_test_[A-Za-z0-9]{10,}",
    r"rk_live_[A-Za-z0-9]{10,}",
    r"SG\.[A-Za-z0-9_-]{10,}",
    r"hf_[A-Za-z0-9]{10,}",
    r"r8_[A-Za-z0-9]{10,}",
    r"npm_[A-Za-z0-9]{10,}",
    r"pypi-[A-Za-z0-9_-]{10,}",
    r"pplx-[A-Za-z0-9]{10,}",
    r"tvly-[A-Za-z0-9]{10,}",
    r"exa_[A-Za-z0-9]{10,}",
    r"fal_[A-Za-z0-9_-]{10,}",
    r"fc-[A-Za-z0-9]{10,}",
    r"dop_v1_[A-Za-z0-9]{10,}",
    r"doo_v1_[A-Za-z0-9]{10,}",
)

_PREFIX_RE = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(_PREFIX_PATTERNS) + r")(?![A-Za-z0-9_-])")

_AUTH_HEADER_RE = re.compile(r"(Authorization:\s*Bearer\s+)(\S+)", re.IGNORECASE)

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----")

# ── Contextual patterns (context-based detection) ────────────────

_SECRET_ENV_NAMES = r"(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)"
_ENV_ASSIGN_RE = re.compile(rf"([A-Z_]{{0,50}}{_SECRET_ENV_NAMES}[A-Z_]{{0,50}})\s*=\s*(['\"]?)(\S+)\2", re.IGNORECASE)

_JSON_KEY_NAMES = (
    r"(?:api_?[Kk]ey|token|secret|password|access_token|"
    r"refresh_token|auth_token|bearer|secret_value|key_material)"
)
_JSON_FIELD_RE = re.compile(rf'("{_JSON_KEY_NAMES}")\s*:\s*"([^"]+)"', re.IGNORECASE)

_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:]+:)([^@]+)(@)", re.IGNORECASE
)

# ── URL Query parameters (OPT-2) ────────────────────────────────
_URL_QUERY_RE = re.compile(r"[?&](?:api_?[Kk]ey|token|secret|password|access_token)=([^&\s]+)", re.IGNORECASE)

# ── CLI flags (OPT-5) ───────────────────────────────────────────
_CLI_FLAG_RE = re.compile(
    r"--(?:api[-_]?key|hook[-_]?token|token|secret|password|passwd)\s+(['\"]?)([^\s'\"]+)\1", re.IGNORECASE
)

# ── Telegram Bot URL (OPT-6) ────────────────────────────────────
_TELEGRAM_BOT_RE = re.compile(r"\bbot(\d{6,}:[A-Za-z0-9_-]{20,})\b", re.IGNORECASE)


def _mask_token(token: str) -> str:
    """Mask a token: fully hide short ones, preserve head/tail for long ones."""
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def redact_sensitive_text(text: str) -> str:
    """Apply all redaction patterns to a block of text.

    Pure function, thread-safe. Returns the input unchanged when
    redaction is disabled via ``MYRM_REDACT_SECRETS=false``.

    Key features:
    - Bounded regex replace to prevent ReDoS (OPT-1)
    - PEM block special handling to preserve header/footer (OPT-3)
    - URL query parameter redaction (OPT-2)
    - CLI flag redaction (OPT-5)
    - Telegram Bot URL redaction (OPT-6)
    - Extended token prefix coverage (Groq, Slack App, Anthropic) (OPT-4)
    """
    if not text or not isinstance(text, str) or not _REDACT_ENABLED:
        return text

    # Use bounded replace for all patterns to prevent ReDoS (OPT-1)
    text = _replace_pattern_bounded(text, _PREFIX_RE, lambda m: _mask_token(m.group(1)))

    text = _replace_pattern_bounded(
        text, _ENV_ASSIGN_RE, lambda m: f"{m.group(1)}={m.group(2)}{_mask_token(m.group(3))}{m.group(2)}"
    )

    text = _replace_pattern_bounded(text, _JSON_FIELD_RE, lambda m: f'{m.group(1)}: "{_mask_token(m.group(2))}"')

    text = _replace_pattern_bounded(text, _AUTH_HEADER_RE, lambda m: m.group(1) + _mask_token(m.group(2)))

    # PEM block special handling: preserve header/footer for debugging (OPT-3)
    text = _replace_pattern_bounded(text, _PRIVATE_KEY_RE, lambda m: _redact_pem_block(m.group(0)))

    text = _replace_pattern_bounded(text, _DB_CONNSTR_RE, lambda m: f"{m.group(1)}***{m.group(3)}")

    # URL query parameters (OPT-2)
    text = _replace_pattern_bounded(
        text, _URL_QUERY_RE, lambda m: m.group(0).replace(m.group(1), _mask_token(m.group(1)))
    )

    # CLI flags (OPT-5)
    text = _replace_pattern_bounded(
        text, _CLI_FLAG_RE, lambda m: m.group(0).replace(m.group(2), _mask_token(m.group(2)))
    )

    # Telegram Bot URL (OPT-6)
    text = _replace_pattern_bounded(
        text, _TELEGRAM_BOT_RE, lambda m: m.group(0).replace(m.group(1), _mask_token(m.group(1)))
    )

    return text


class RedactingFormatter(logging.Formatter):
    """Log formatter that redacts secrets from all messages."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


# ── Invisible Unicode escaping (approval display) ─────────────

_INVISIBLE_CODEPOINTS: frozenset[int] = frozenset(
    {
        0x200B,  # zero width space
        0x200C,  # zero width non-joiner
        0x200D,  # zero width joiner
        0xFEFF,  # byte order mark / zero width no-break space
        0x2060,  # word joiner
        0x2061,  # function application
        0x2062,  # invisible times
        0x2063,  # invisible separator
        0x2064,  # invisible plus
        0x00AD,  # soft hyphen
        0x034F,  # combining grapheme joiner
        0x061C,  # Arabic letter mark
        0x180E,  # Mongolian vowel separator
    }
)

_INVISIBLE_ESCAPE_RE = re.compile("[" + "".join(f"\\u{cp:04X}" for cp in sorted(_INVISIBLE_CODEPOINTS)) + "]")


def escape_invisible_unicode(text: str) -> str:
    r"""Replace invisible Unicode codepoints with visible ``\u{XXXX}`` escapes.

    Unlike ``content_boundary.strip_invisible_unicode`` (which removes them),
    this preserves evidence of their presence for human review in approval UIs.
    """
    if not text:
        return text
    return _INVISIBLE_ESCAPE_RE.sub(lambda m: f"\\u{{{ord(m.group()):04X}}}", text)


def _redact_value_recursive(obj: object) -> object:
    """Recursively redact string values in dicts/lists."""
    if isinstance(obj, str):
        return redact_sensitive_text(escape_invisible_unicode(obj))
    if isinstance(obj, dict):
        return {k: _redact_value_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_value_recursive(item) for item in obj]
    return obj


def redact_for_display(args: dict[str, object]) -> dict[str, object]:
    """Redact tool arguments for approval UI display.

    Applies invisible Unicode escaping + secret masking recursively.
    Used by the approval batch processor to sanitize args before
    sending them to the frontend. The original args are preserved
    for actual tool execution.
    """
    result = _redact_value_recursive(args)
    if not isinstance(result, dict):
        return args
    return result
