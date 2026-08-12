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

Coverage:
- Token-prefix patterns (sk-/ghp_/AKIA/… 25+), PEM blocks, DB connection strings
- Contextual: ENV assignments (uppercase + lowercase/short names, query-parameter guarded), JSON fields, Authorization (any scheme)
- Config formats: unquoted YAML/colon (`password: secret`), form-urlencoded bodies (`token=abc&page=1` → pair-wise redaction)
- Word-boundary key validation (``author=``/``tokenizer=`` prose not redacted)
- URL: query params, userinfo (user:pass@), bare-token (TOKEN@), Telegram bot URLs
- Headers: x-api-key style auth headers; structure: bare JWTs
- Control/zero-width char split-token bypass guard (对齐 Hermes issue #77484)
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

# Authorization headers — any scheme (Bearer, Basic, Token, Digest, …) plus the
# bare-credential form, and Proxy-Authorization. The credential token is masked
# while the header name and scheme word are preserved for debuggability. Quote
# characters are excluded from the credential class so a token flush against a
# closing quote cannot pull that quote into the match (which would corrupt
# command/string syntax for the LLM consumer).
_AUTH_HEADER_RE = re.compile(
    r"((?:Proxy-)?Authorization:\s*)([A-Za-z][\w.+-]*\s+)?([^\s\"']+)",
    re.IGNORECASE,
)

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----")

# ── Contextual patterns (context-based detection) ────────────────

_SECRET_ENV_NAMES = r"(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)"
# URL query 中的 `?token=` / `&token=` 是 URL 参数（由 _URL_QUERY_RE 处理），不是
# ENV 赋值——负向后顾阻止贪婪吞掉 `&` 分隔的后续参数
# （`?token=x&limit=50&page=2` 保持为 `?token=***&limit=50&page=2` 而非 `?token=***`）。
# value 用 `[^&\s]+` 而非 `\S+`：IGNORECASE 下 form body 的 `token=abc&page=1` 会被
# `\S+` 吞掉 `&page=1` 导致参数破坏，`[^&\s]+` 在 `&` 处截断，配合 _redact_form_body
# 逐对脱敏（对齐 Hermes 非 IGNORECASE 正则的天然行为）。
# key 必须含 secret 关键词且关键词落在词边界（`author=`/`tokenizer=` 等散文词
# 不误伤，见 _key_has_secret_keyword）。
_ENV_ASSIGN_RE = re.compile(
    rf"(?<![?&])([A-Z_]{{0,50}}{_SECRET_ENV_NAMES}[A-Z_]{{0,50}})\s*=\s*(['\"]?)([^\s&]+)\2",
    re.IGNORECASE,
)

# 小写/短名 env 赋值（`db_pw=`/`openai_key=`/`FAL_KEY=`）：仅下划线分隔的短名形式。
# 裸 `password=`/`token=`/`secret=` 不匹配——它们出现在散文、URL query 与 form body
# 中（对齐 Hermes issue #77484）。词边界落在下划线处，`author=` 不误伤。
_ENV_ASSIGN_LOWER_RE = re.compile(
    rf"([a-z0-9_]+(?:_|^)(?:key|pass|pw|token|secret|password|passwd|credential|auth)(?=[^a-z0-9_]|$))\s*=\s*(['\"]?)([^\s&]+)\2",
    re.IGNORECASE,
)

# YAML / 冒号式配置（`password: secret`、`spring.datasource.password: hunter2`、
# `password: "hunter2!"`）。secret 关键词必须在 key 中（锚定行首/缩进），value
# 为单个无空白 token——`note: secret meeting`（关键词在 value）与
# `error: token expired` 不匹配。裸 `auth` 排除在 key 名单外，`Authorization:`/
# `author:` 不误伤（前者由 _AUTH_HEADER_RE 处理）；`auth_token`/`auth-token` 经
# `token` 关键词仍匹配。可选引号保留引号结构（quoted 值含空格的极罕见场景不匹配，
# 与 JSON 的 `"password"` key 形式互斥）。
_YAML_CFG_NAMES = r"(?:api[ _.\-]?key|token|secret|passwd|password|credential)"
_YAML_ASSIGN_RE = re.compile(
    rf"(^[ \t]*+[A-Za-z0-9_.\-]*{_YAML_CFG_NAMES}[A-Za-z0-9_.\-]*+)(:[ \t]*+)(['\"]?)([^\s&]+)\3",
    re.IGNORECASE | re.MULTILINE,
)

# ── 词边界校验（对齐 Hermes issue #6129）───────────────────────
# key 类允许关键词带任意字母数字前后缀（`client_secret`/`clientSecret`/`s3.secret-key`），
# 副作用是 `secretary`/`tokenizer`/`authored` 等散文词也命中。keyword 只有落在词边界
# （key 边缘、非字母旁、camelCase 转换、全大写缩写边界）才算凭据；内嵌于更长单词的
# 不匹配。ALL-CAPS key 保留旧嵌入匹配（`MYTOKEN=` 几乎不可能是散文）。
_KEY_KEYWORD_RE = re.compile(
    r"(?:api|auth|access|refresh|session|secret)[ _.\\-]?(?:key|token)"
    r"|token|secret|passwd|password|pass|pw|credential|auth|key",
    re.IGNORECASE,
)


def _is_word_start(s: str, i: int) -> bool:
    """位置 ``i`` 是否处于单词开头（非词中）。"""
    if i == 0:
        return True
    prev, cur = s[i - 1], s[i]
    if not prev.isalpha():
        return True
    if cur.isupper() and prev.islower():
        return True  # camelCase: clientSecret
    # 缩写序列结尾：APIToken —— 前一大写后一小写
    if cur.isupper() and prev.isupper() and i + 1 < len(s) and s[i + 1].islower():
        return True
    return False


def _is_word_end(s: str, j: int, *, allow_plural: bool = True) -> bool:
    """位置 ``j``（exclusive）是否处于单词结尾。"""
    if j >= len(s):
        return True
    cur = s[j]
    if not cur.isalpha():
        return True
    if cur.isupper() and s[j - 1].islower():
        return True  # camelCase 延续: secretKey
    if allow_plural and cur in "sS":
        return _is_word_end(s, j + 1, allow_plural=False)
    return False


def _key_has_secret_keyword(key: str) -> bool:
    """key 是否在词边界处含 secret 关键词。

    过滤 `secretary`/`tokenizer`/`authored` 等嵌词误伤。ALL-CAPS key 短路到旧嵌入
    匹配：`KEYBOARD`/`PASSAGE` 这类关键词内嵌于更长全大写单词的仍拒绝。
    """
    letters = [c for c in key if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        for m in _KEY_KEYWORD_RE.finditer(key):
            if _is_word_start(key, m.start()) and _is_word_end(key, m.end()):
                return True
        return False
    for m in _KEY_KEYWORD_RE.finditer(key):
        if _is_word_start(key, m.start()) and _is_word_end(key, m.end()):
            return True
    return False


# ── Form-urlencoded body（`token=abc&limit=50&page=2`）──────────
# 保守判定：整段文本呈纯 k=v&k=v 且无换行才触发。逐对脱敏，只打码敏感 key 的 value，
# 其余参数原样保留（杜绝 ENV 正则 `\S+` 贪婪吞参导致 `token=abc&li...ge=2` 泄漏）。
_SENSITIVE_BODY_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "api_key",
        "apikey",
        "client_secret",
        "password",
        "auth",
        "jwt",
        "secret",
        "private_key",
        "authorization",
        "key",
    }
)
_FORM_BODY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*=[^&\s]*(?:&[A-Za-z_][A-Za-z0-9_.-]*=[^&\s]*)+$")


def _redact_form_body(text: str) -> str:
    """脱敏 form-urlencoded body 中的敏感参数值。

    仅在整段文本呈纯 k=v&k=v 时触发；含换行或混排文本放行（URL query 已由
    _URL_QUERY_RE 覆盖）。逐参数判定，非敏感 key 原样保留。
    """
    if not text or "\n" in text or "&" not in text:
        return text
    stripped = text.strip()
    if not _FORM_BODY_RE.match(stripped):
        return text
    parts: list[str] = []
    for pair in stripped.split("&"):
        if "=" not in pair:
            parts.append(pair)
            continue
        key, _, value = pair.partition("=")
        if key.lower() in _SENSITIVE_BODY_KEYS:
            parts.append(f"{key}=***")
        else:
            parts.append(pair)
    return "&".join(parts)

# 程序化 env 引用（`os.getenv('X')` / `os.environ[...]` / `process.env.X` / `$ENV{X}`）
# 是变量名引用而非凭据值——掩码会破坏代码示例的可读性（对齐 Hermes 的 guard）。
_ENV_LOOKUP_VALUE_RE = re.compile(
    r"^(?:os\.(?:getenv|environ)|process\.env|\$ENV\{)",
)

_JSON_KEY_NAMES = (
    r"(?:api_?[Kk]ey|token|secret|password|access_token|"
    r"refresh_token|auth_token|bearer|secret_value|key_material)"
)
_JSON_FIELD_RE = re.compile(rf'("{_JSON_KEY_NAMES}")\s*:\s*"([^"]+)"', re.IGNORECASE)

_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:]+:)([^@]+)(@)", re.IGNORECASE
)

# ── URL Query parameters (OPT-2) ────────────────────────────────
# key=value 分组捕获，替换仅作用于 value，避免 value 是 key 名字符子串时
# `.replace()` 连带破坏 key 名（`?api_key=a` 误伤为 `?***pi_key=***`）。
# key 名单必须 ⊇ _SECRET_ENV_NAMES（ENV 正则加负向后顾后不再兜底 URL 参数，
# 若名单不一致，`?credential=`/`?auth=` 会双双落空而明文泄漏）。
# 追加下划线边界短名（`?openai_key=`/`?db_pw=`/`?FAL_KEY=`）——URL 中同样存在
# 小写短名凭据参数，与 _ENV_ASSIGN_LOWER_RE 的短名集合保持一致。
_URL_QUERY_KEYS = rf"{_SECRET_ENV_NAMES}|access_token|api_?[Kk]ey|[a-z0-9_]+_(?:key|pass|pw|token|secret|password|passwd|credential|auth)"
_URL_QUERY_RE = re.compile(rf"([?&](?:{_URL_QUERY_KEYS})=)([^&\s]+)", re.IGNORECASE)

# ── CLI flags (OPT-5) ───────────────────────────────────────────
# flag 名、引号、value 分组捕获，替换仅作用于 value，避免短 value 误伤 flag 名
# （`--secret s` 误伤为 `--***ecret ***`）。
_CLI_FLAG_RE = re.compile(
    r"(--(?:api[-_]?key|hook[-_]?token|token|secret|password|passwd)\s+)(['\"]?)([^\s'\"]+)\2",
    re.IGNORECASE,
)

# ── Telegram Bot URL (OPT-6) ────────────────────────────────────
_TELEGRAM_BOT_RE = re.compile(r"\b(bot)(\d{6,}:[A-Za-z0-9_-]{20,})\b", re.IGNORECASE)

# ── URL userinfo / bare-token (对齐 Hermes) ─────────────────────
# `scheme://user:password@host` 的密码段掩码，用户名保留用于可读性。
# 数据库协议（postgres/mysql/mongodb/redis/amqp）已由 _DB_CONNSTR_RE 覆盖。
_URL_USERINFO_RE = re.compile(
    r"(https?|wss?|ftp)://([^/\s:@]+):([^/\s@]+)@",
    re.IGNORECASE,
)

# `scheme://TOKEN@host`（无冒号 bare-token userinfo，如 git 私有仓库 URL）。
# 8+ 字符避免误伤短用户名。对齐 Hermes #6396。
_URL_BARE_TOKEN_RE = re.compile(
    r"((?:https?|wss?|git|ssh|ftp|ftps|sftp)://)([^\s:@/]{8,})(@[^\s]+)",
    re.IGNORECASE,
)

# ── API-key 风格认证头 (对齐 Hermes _SECRET_HEADER_RE) ──────────
_SECRET_HEADER_NAMES = (
    r"(?:x-api-key|x-goog-api-key|api-key|apikey|x-api-token|x-auth-token|x-access-token)"
)
_SECRET_HEADER_RE = re.compile(rf"({_SECRET_HEADER_NAMES}\s*:\s*)(\S+)", re.IGNORECASE)

# ── JWT token (对齐 Hermes _JWT_RE) ──────────────────────────────
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")

# ── 控制字符拆分 token 防护 (对齐 Hermes issue #77484) ─────────
# 控制/零宽字符（ESC、零宽空格、换行等）可拆分 token body，使 _PREFIX_RE 无法
# 连续匹配 —— `sk-abc\x1bdef…` 凭据因此绕过脱敏泄漏。策略：剥离控制字符后
# 匹配，再映射回原文对应 span 掩码；仅当 span 内全部为 token-body 或控制
# 字符时才掩码，避免跨行误伤无关文本。
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x1f\x7f\u200b-\u200f\u2028-\u202f\u2060\ufeff]"
)
_TOKEN_BODY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-."
)


def _mask_token(token: str) -> str:
    """Mask a token: fully hide short ones, preserve head/tail for long ones."""
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


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
    stripped = _CONTROL_CHARS_RE.sub("", text)
    if stripped == text:
        return text
    orig_idx = [i for i, c in enumerate(text) if not _CONTROL_CHARS_RE.match(c)]
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


def _redact_env_assignment(m: re.Match[str]) -> str:
    """Replacement for _ENV_ASSIGN_RE — skip programmatic env lookups and prose keys.

    ``OPENAI_API_KEY=os.getenv('OPENAI_API_KEY')`` references a variable by
    name, not a secret value; masking it corrupts code snippets in
    prose/log contexts. Keys whose secret keyword is not at a word boundary
    (``author=Smith``, ``tokenizer=cl100k``) are prose, not credentials
    (aligned with Hermes issue #6129). Any other matched ``KEY=value`` is
    masked normally.
    """
    name, quote, value = m.group(1), m.group(2), m.group(3)
    if _ENV_LOOKUP_VALUE_RE.match(value):
        return m.group(0)
    if not _key_has_secret_keyword(name):
        return m.group(0)
    return f"{name}={quote}{_mask_token(value)}{quote}"


def _redact_lower_env_assignment(m: re.Match[str]) -> str:
    """Replacement for _ENV_ASSIGN_LOWER_RE — same guards as _redact_env_assignment."""
    name, quote, value = m.group(1), m.group(2), m.group(3)
    if _ENV_LOOKUP_VALUE_RE.match(value):
        return m.group(0)
    if not _key_has_secret_keyword(name):
        return m.group(0)
    return f"{name}={quote}{_mask_token(value)}{quote}"


def _redact_yaml_assignment(m: re.Match[str]) -> str:
    """Replacement for _YAML_ASSIGN_RE / _YAML_QUOTED_ASSIGN_RE.

    Skip programmatic lookups and prose keys. ``api_key: os.getenv('X')``
    references a variable name (issue #2852); ``secretary: J.Smith`` /
    ``tokenizer: cl100k_base`` embed a keyword mid-word (issue #6129). Both
    pass through unchanged. Quoted values keep their quotes.
    """
    key, sep, quote, value = m.group(1), m.group(2), m.group(3), m.group(4)
    if _ENV_LOOKUP_VALUE_RE.match(value):
        return m.group(0)
    if not _key_has_secret_keyword(key):
        return m.group(0)
    return f"{key}{sep}{quote}{_mask_token(value)}{quote}"


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

    # 控制字符拆分的 token（`sk-abc\x1bdef…`）在连续 _PREFIX_RE 之前先掩码
    text = _mask_control_split_tokens(text)

    # Form-urlencoded body（`token=abc&limit=50&page=2`）：整段 k=v&k=v 时逐对脱敏，
    # 必须在 ENV 正则之前——否则 `\S+` 贪婪吞掉 `&` 分隔的后续参数并泄漏前缀
    text = _redact_form_body(text)

    # Use bounded replace for all patterns to prevent ReDoS (OPT-1)
    text = _replace_pattern_bounded(text, _PREFIX_RE, lambda m: _mask_token(m.group(1)))

    text = _replace_pattern_bounded(text, _ENV_ASSIGN_RE, _redact_env_assignment)

    # 小写/短名 env（`db_pw=`/`openai_key=`）。跳过 URL——query string 中的
    # `token=`/`key=` 参数可能是有意放行的（_URL_QUERY_RE 处理凭据参数）。
    if "://" not in text:
        text = _replace_pattern_bounded(text, _ENV_ASSIGN_LOWER_RE, _redact_lower_env_assignment)

    text = _replace_pattern_bounded(text, _JSON_FIELD_RE, lambda m: f'{m.group(1)}: "{_mask_token(m.group(2))}"')

    # Unquoted / quoted YAML-colon config（`password: secret`、`password: "hunter2!"`）。
    # URL（含 `://`）不放行 YAML 误伤。
    if "://" not in text:
        text = _replace_pattern_bounded(text, _YAML_ASSIGN_RE, _redact_yaml_assignment)

    text = _replace_pattern_bounded(
        text,
        _AUTH_HEADER_RE,
        lambda m: f"{m.group(1)}{m.group(2) or ''}{_mask_token(m.group(3))}",
    )

    # PEM block special handling: preserve header/footer for debugging (OPT-3)
    text = _replace_pattern_bounded(text, _PRIVATE_KEY_RE, lambda m: _redact_pem_block(m.group(0)))

    text = _replace_pattern_bounded(text, _DB_CONNSTR_RE, lambda m: f"{m.group(1)}***{m.group(3)}")

    # URL userinfo（`https://user:pass@host`）与 bare-token（`https://TOKEN@host`）
    text = _replace_pattern_bounded(
        text, _URL_USERINFO_RE, lambda m: f"{m.group(1)}://{m.group(2)}:***@"
    )
    text = _replace_pattern_bounded(
        text, _URL_BARE_TOKEN_RE, lambda m: f"{m.group(1)}{_mask_token(m.group(2))}{m.group(3)}"
    )

    # URL query parameters (OPT-2)
    text = _replace_pattern_bounded(
        text, _URL_QUERY_RE, lambda m: f"{m.group(1)}{_mask_token(m.group(2))}"
    )

    # CLI flags (OPT-5)
    text = _replace_pattern_bounded(
        text, _CLI_FLAG_RE, lambda m: f"{m.group(1)}{m.group(2)}{_mask_token(m.group(3))}{m.group(2)}"
    )

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
