"""Regex-based secret redaction for tool output and logs.

Applies pattern matching to mask API keys, tokens, and credentials
before they reach the LLM context or log files. Acts as a second
defense layer complementing ``sanitize_env`` (source removal).

[INPUT]
- (none — pure data + logic module)

[OUTPUT]
- redact_sensitive_text(text) -> str — apply all redaction patterns
- redact_for_llm(value) -> str — recursive redaction of nested diagnostic values, flattened to str (LLM error formatting)
- escape_invisible_unicode(text) -> str — escape invisible chars to \\u{XXXX}
- redact_for_display(args) -> dict — recursive redaction for approval UI
- RedactingFormatter — logging.Formatter subclass for production logs

Pattern definitions live in ``patterns.py``; this module owns the redaction
engine (bounded replace, control-split guard, pipeline) and public APIs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from .patterns import (
    _AUTH_HEADER_RE,
    _CLI_FLAG_RE,
    _CONTROL_CHARS_RE,
    _DB_CONNSTR_RE,
    _ENV_ASSIGN_LOWER_RE,
    _ENV_ASSIGN_RE,
    _JSON_FIELD_RE,
    _JWT_RE,
    _PREFIX_RE,
    _PRIVATE_KEY_RE,
    _SECRET_HEADER_RE,
    _TELEGRAM_BOT_RE,
    _TOKEN_BODY_CHARS,
    _URL_BARE_TOKEN_RE,
    _URL_QUERY_RE,
    _URL_USERINFO_RE,
    _YAML_ASSIGN_RE,
    _mask_token,
    _redact_cli_flag,
    _redact_env_assignment,
    _redact_form_body,
    _redact_yaml_assignment,
)

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
        # 分块重叠区可能产出区间重叠的 match（如 IGNORECASE 下 `[A-Z_]` 前缀贪婪
        # 吃掉 `KEY` 前 50 个连续字母产生长 key match，与后续短 key match 区间重叠）。
        # 重叠 match 若一并拼接会把文本重复插入，须跳过（seen_starts 只防同 start）。
        if abs_start < last_end:
            continue
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


def _mask_control_split_tokens(text: str) -> str:
    """Mask tokens whose body is split by control/zero-width characters.

    A credential like ``sk-abc\\x1bdef456…`` has its token body interrupted,
    so the contiguous ``_PREFIX_RE`` cannot match it and the secret leaks
    verbatim. Strategy: build a copy with all control chars removed (the token
    is contiguous again), match on that, then mask the corresponding span in
    the *original* — but only when the original span contains solely token-body
    and control chars (a match that crosses into a different line's unrelated
    text is rejected).
    """
    control_pos = {m.start() for m in _CONTROL_CHARS_RE.finditer(text)}
    if not control_pos:
        return text
    stripped = "".join(c for i, c in enumerate(text) if i not in control_pos)
    orig_idx = [i for i in range(len(text)) if i not in control_pos]
    out = list(text)
    matches: list[tuple[int, int, str]] = []
    for m in _PREFIX_RE.finditer(stripped):
        body = m.group(1)
        start_orig = orig_idx[m.start(1)]
        end_orig = orig_idx[m.end(1) - 1] + 1
        span = text[start_orig:end_orig]
        # If a fragment inside the span already matches _PREFIX_RE on its own
        # AND the span crosses a LINE boundary (\n / \r), do NOT join: a
        # complete token at end-of-line followed by a word line
        # (``ghp_<token>\nbutton [ref=e3]``) joins into one stripped-copy match
        # and the mask would eat ``button``. For NON-newline controls (ESC,
        # ZWSP, ...) the join proceeds even when a fragment self-matches, so a
        # split token (``sk-<head>\x1b<tail>``) is masked in full.
        if ("\n" in span or "\r" in span) and _PREFIX_RE.search(span):
            continue
        # Reject matches whose original span crosses a non-token char
        # (e.g. ``sk_abc…\nTAVILY_API_KEY=…`` — the ``=`` is not part of a token
        # body, so the regex matched across unrelated lines).
        if not (
            all(c in _TOKEN_BODY_CHARS or _CONTROL_CHARS_RE.match(c) for c in span)
            and (end_orig >= len(text) or text[end_orig] != "=")
        ):
            continue
        matches.append((start_orig, end_orig, _mask_token(body)))
    for start_orig, end_orig, replacement in reversed(matches):
        out[start_orig:end_orig] = list(replacement)
    return "".join(out)


def redact_sensitive_text(text: str) -> str:
    """Apply all redaction patterns to a block of text.

    Pure function, thread-safe. Returns the input unchanged when
    redaction is disabled via ``MYRM_REDACT_SECRETS=false``.

    Key features:
    - Bounded regex replace to prevent ReDoS (OPT-1)
    - Control/zero-width split-token masking before prefix matching
    - Form-urlencoded body pair-wise redaction (no parameter swallowing)
    - YAML/colon config redaction (unquoted + quoted values)
    - ENV assignment redaction with word-boundary key validation
    - PEM block special handling to preserve header/footer (OPT-3)
    - URL query parameter redaction (OPT-2)
    - CLI flag redaction (OPT-5)
    - Telegram Bot URL redaction (OPT-6)
    - Extended token prefix coverage (Groq, Slack App, Anthropic) (OPT-4)
    """
    if not text or not isinstance(text, str) or not _REDACT_ENABLED:
        return text

    # 控制字符拆分的 token（`sk-abc\x1bdef…`）在连续 _PREFIX_RE 之前先掩码
    text = _mask_control_split_tokens(text)

    # Form-urlencoded body（`token=abc&limit=50&page=2`）：整段 k=v&k=v 时逐对脱敏，
    # 必须在 ENV 正则之前——否则 `\S+` 贪婪吞掉 `&` 分隔的后续参数并泄漏前缀
    text = _redact_form_body(text)

    # Use bounded replace for all patterns to prevent ReDoS (OPT-1)
    text = _replace_pattern_bounded(text, _PREFIX_RE, lambda m: _mask_token(m.group(1)))

    text = _replace_pattern_bounded(text, _ENV_ASSIGN_RE, _redact_env_assignment)

    # 小写/短名 env（`db_pw=`/`openai_key=`）。`(?<![?&])` 负向后顾已阻止 URL query
    # 参数（由 _URL_QUERY_RE 处理），此处无条件执行——含 URL 的混合文本同样脱敏。
    text = _replace_pattern_bounded(text, _ENV_ASSIGN_LOWER_RE, _redact_env_assignment)

    text = _replace_pattern_bounded(
        text, _JSON_FIELD_RE, lambda m: f'{m.group(1)}: "{_mask_token(m.group(2))}"'
    )

    # Unquoted / quoted YAML-colon config（`password: secret`、`password: "hunter2!"`）。
    # 正则锚定行首且 key 字符类不含 `:`/`/`/`?`，天然不匹配 URL 行，无需全局 URL 开关。
    text = _replace_pattern_bounded(text, _YAML_ASSIGN_RE, _redact_yaml_assignment)

    text = _replace_pattern_bounded(
        text,
        _AUTH_HEADER_RE,
        lambda m: f"{m.group(1)}{m.group(2) or ''}{_mask_token(m.group(3))}",
    )

    # PEM block special handling: preserve header/footer for debugging (OPT-3)
    text = _replace_pattern_bounded(
        text, _PRIVATE_KEY_RE, lambda m: _redact_pem_block(m.group(0))
    )

    text = _replace_pattern_bounded(
        text, _DB_CONNSTR_RE, lambda m: f"{m.group(1)}***{m.group(3)}"
    )

    # URL userinfo（`https://user:pass@host`）与 bare-token（`https://TOKEN@host`）
    text = _replace_pattern_bounded(
        text, _URL_USERINFO_RE, lambda m: f"{m.group(1)}://{m.group(2)}:***@"
    )
    text = _replace_pattern_bounded(
        text,
        _URL_BARE_TOKEN_RE,
        lambda m: f"{m.group(1)}{_mask_token(m.group(2))}{m.group(3)}",
    )

    # URL query parameters (OPT-2)
    text = _replace_pattern_bounded(
        text, _URL_QUERY_RE, lambda m: f"{m.group(1)}{_mask_token(m.group(2))}"
    )

    # CLI flags (OPT-5)
    text = _replace_pattern_bounded(text, _CLI_FLAG_RE, _redact_cli_flag)

    # Telegram Bot URL (OPT-6)
    text = _replace_pattern_bounded(
        text, _TELEGRAM_BOT_RE, lambda m: f"{m.group(1)}{_mask_token(m.group(2))}"
    )

    # API-key 风格认证头（x-api-key 等）
    text = _replace_pattern_bounded(
        text, _SECRET_HEADER_RE, lambda m: f"{m.group(1)}{_mask_token(m.group(2))}"
    )

    # JWT token（eyJ… 无 key 上下文的裸 JWT）
    text = _replace_pattern_bounded(text, _JWT_RE, lambda m: _mask_token(m.group(0)))

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

_INVISIBLE_ESCAPE_RE = re.compile(
    "[" + "".join(f"\\u{cp:04X}" for cp in sorted(_INVISIBLE_CODEPOINTS)) + "]"
)


def escape_invisible_unicode(text: str) -> str:
    r"""Replace invisible Unicode codepoints with visible ``\u{XXXX}`` escapes.

    Unlike ``content_boundary.strip_invisible_unicode`` (which removes them),
    this preserves evidence of their presence for human review in approval UIs.
    """
    if not text:
        return text
    return _INVISIBLE_ESCAPE_RE.sub(lambda m: f"\\u{{{ord(m.group()):04X}}}", text)


def redact_for_llm(value: object) -> str:
    """Redact credentials from a nested diagnostic value, flattened to a string.

    Recursively masks secret strings inside dict/list/tuple values before the
    text reaches the LLM. Keeps the exact string shape of the original nested
    structure (list-style brackets for both list and tuple containers).
    """
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return str({k: redact_for_llm(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return str([redact_for_llm(v) for v in value])
    return str(value)


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
