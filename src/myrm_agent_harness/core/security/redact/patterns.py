"""Regex pattern definitions for secret redaction.

Single source of truth for secret-detection patterns used by the redaction
engine (``engine.py``) and structured content sanitizers (e.g.
``agent/skills/security/content_sanitizer.py``). Holds the compiled regexes,
word-boundary key validation, and shared value-masking helpers.

[INPUT]
- (none — pure pattern + helper definitions)

[OUTPUT]
- compiled detection regexes (``_PREFIX_RE``, ``_ENV_ASSIGN_RE``, ...)
- ``_mask_token`` / ``_redact_form_body`` / ``_redact_*_assignment`` — shared replacers
- ``_is_word_start`` / ``_is_word_end`` / ``_key_has_secret_keyword`` — word-boundary key validation
"""

from __future__ import annotations

import re

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
    r"xapp-\d+-[A-Za-z0-9-]{10,}",  # Slack App (OPT-4)
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
    # 以下为对齐 Hermes _PREFIX_PATTERNS 补充的服务商前缀
    r"bb_live_[A-Za-z0-9_-]{10,}",  # BrowserBase
    r"gAAAA[A-Za-z0-9_=-]{20,}",  # Codex encrypted tokens
    r"am_[A-Za-z0-9_-]{10,}",  # AgentMail
    r"sk_[A-Za-z0-9_]{10,}",  # ElevenLabs TTS（下划线分隔，与 sk- 区分）
    r"syt_[A-Za-z0-9]{10,}",  # Matrix access token
    r"retaindb_[A-Za-z0-9]{10,}",  # RetainDB
    r"hsk-[A-Za-z0-9]{10,}",  # Hindsight
    r"mem0_[A-Za-z0-9]{10,}",  # Mem0 Platform
    r"brv_[A-Za-z0-9]{10,}",  # ByteRover
    r"xai-[A-Za-z0-9]{30,}",  # xAI (Grok)
    r"ntn_[A-Za-z0-9]{10,}",  # Notion internal integration
    r"fw-[A-Za-z0-9]{30,}",  # Fireworks AI
    r"fw_[A-Za-z0-9]{30,}",  # Fireworks AI
    r"fpk_[A-Za-z0-9]{30,}",  # Fireworks AI project key
    # GitLab token 家族
    r"glpat-[A-Za-z0-9_\-]{10,}",  # personal access token
    r"gloas-[A-Za-z0-9_\-]{10,}",  # OAuth application secret
    r"gldt-[A-Za-z0-9_\-]{10,}",  # deploy token
    r"glrt-[A-Za-z0-9_.\-]{10,}",  # runner authentication token
    r"glrtr-[A-Za-z0-9_.\-]{10,}",  # runner registration token
    r"glcbt-[A-Za-z0-9_\-]{10,}",  # CI/CD job token
    r"glptt-[A-Za-z0-9_\-]{10,}",  # pipeline trigger token
    r"glft-[A-Za-z0-9_\-]{10,}",  # feed token
    r"glimt-[A-Za-z0-9_\-]{10,}",  # incoming mail token
    r"glagent-[A-Za-z0-9_\-]{10,}",  # agent (KAS) token
    r"glsoat-[A-Za-z0-9_\-]{10,}",  # service-account access token
    r"glffct-[A-Za-z0-9_\-]{10,}",  # feature-flags client token
    r"glwt-[A-Za-z0-9_\-]{10,}",  # workspace token
    r"GR1348941[A-Za-z0-9_\-]{10,}",  # legacy runner registration token
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
# value 用 `[^\s&"']` 而非 `\S+`：IGNORECASE 下 form body 的 `token=abc&page=1` 会被
# `\S+` 吞掉 `&page=1` 导致参数破坏，`[^\s&]+` 在 `&` 处截断，配合 _redact_form_body
# 逐对脱敏（对齐 Hermes 非 IGNORECASE 正则的天然行为）。引号值整体捕获
# （`KEY="my secret pass"` 含空格）——quote 分支吞到 closing quote，避免部分匹配
# 把 `"my` 打码而泄漏尾部 ` secret pass"`；值内 `\"`/`\'` 反斜杠转义与 `''` 转义
# 均完整消费不截断。
# key 必须含 secret 关键词且关键词落在词边界（`author=`/`tokenizer=` 等散文词
# 不误伤，见 _key_has_secret_keyword）。
_ENV_ASSIGN_RE = re.compile(
    rf"(?<![?&])([A-Z_]{{0,50}}{_SECRET_ENV_NAMES}[A-Z_]{{0,50}})\s*=\s*((?:(['\"])(?:[^'\"\\\\]|''|\\.)*\3)|(?:[^\s&\"']+))",
    re.IGNORECASE,
)

# 小写/短名 env 赋值（`db_pw=`/`openai_key=`/`FAL_KEY=`）：key 以下划线或点分隔短名形式
# （点分隔覆盖 `app.api.key=`/`s3.secret-key=` 等点分配置，对齐 Hermes _CFG_DOTTED_RE；
# `end.key=` 由 _key_has_secret_keyword 词边界校验放行，`file.txt=` 因 `txt` 非关键词不匹配）。
# 裸 `password=`/`token=`/`secret=` 不匹配——它们出现在散文、URL query 与 form body
# 中（对齐 Hermes issue #77484）。`[a-z0-9_]*` 后缀覆盖下划线续接名
# （`openai_key_legacy=`），词边界校验兜底防 `db_pwx=` 类吞词误伤。
# `(?<![?&])` 负向后顾（与 _ENV_ASSIGN_RE 一致）阻止 URL query 参数
# （`?openai_key=`/`&openai_key=` 交给 _URL_QUERY_RE 处理），从而无需全局 URL 开关。
# 前缀限长 `{1,64}`：无界 `[a-z0-9_.]+` 在无下划线长文本上逐位回溯 O(n²)（32KB
# 纯文本 6s+），限长后恒 O(n·64)。
_ENV_ASSIGN_LOWER_RE = re.compile(
    r"(?<![?&])([a-z0-9_.]{1,64}[_.](?:key|pass|pw|token|secret|password|passwd|credential|auth)[a-z0-9_]*)(?=[^a-z0-9_]|$)\s*=\s*((?:(['\"])(?:[^'\"\\\\]|''|\\.)*\3)|(?:[^\s&\"']+))",
    re.IGNORECASE,
)

# YAML / 冒号式配置（`password: secret`、`spring.datasource.password: hunter2`、
# `password: "hunter2!"`、`password : secret`）。secret 关键词必须在 key 中
# （锚定行首/缩进），value 为单个无空白 token——`note: secret meeting`
# （关键词在 value）与 `error: token expired` 不匹配。裸 `auth`（对齐 Hermes）
# 覆盖 `auth: <secret>`，`author:`/`Authorization:` 由词边界校验（_key_has_secret_keyword）
# 与 _AUTH_HEADER_RE 拦截，不误伤。可选引号保留引号结构：双引号支持 `\"` 转义，
# 单引号支持 YAML `''` 转义，quoted 值含空格时整体捕获不部分泄漏。
_YAML_CFG_NAMES = r"(?:api[ _.\-]?key|token|secret|passwd|password|credential|auth)"
_YAML_ASSIGN_RE = re.compile(
    rf"(^[ \t]*+[A-Za-z0-9_.\-]*{_YAML_CFG_NAMES}[A-Za-z0-9_.\-]*+)([ \t]*+:[ \t]*+)((?:(['\"])(?:[^'\"\\\\]|''|\\.)*\4)|(?:[^\s&\"']+))",
    re.IGNORECASE | re.MULTILINE,
)

# ── 词边界校验（对齐 Hermes issue #6129）───────────────────────
# key 类允许关键词带任意字母数字前后缀（`client_secret`/`clientSecret`/`s3.secret-key`），
# 副作用是 `secretary`/`tokenizer`/`authored` 等散文词也命中。keyword 只有落在词边界
# （key 边缘、非字母旁、camelCase 转换、全大写缩写边界）才算凭据；内嵌于更长单词的
# 不匹配。ALL-CAPS key 同样要求词边界——`MYTOKEN` 不匹配而 `MY_TOKEN` 匹配。
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
    return cur.isupper() and prev.isupper() and i + 1 < len(s) and s[i + 1].islower()


def _is_word_end(s: str, j: int, *, allow_plural: bool = True) -> bool:
    """位置 ``j``（exclusive）是否处于单词结尾。"""
    if j == 0 or j >= len(s):
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

    过滤 `secretary`/`tokenizer`/`authored`/`KEYBOARD` 等嵌词误伤——关键词必须
    落在词边界（key 边缘、非字母旁、camelCase/缩写转换处）才算凭据。
    """
    return any(_is_word_start(key, m.start()) and _is_word_end(key, m.end()) for m in _KEY_KEYWORD_RE.finditer(key))


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
        "api-key",
        "x-api-key",
        "x-goog-api-key",
        "api_token",
        "auth_token",
        "client_secret",
        "password",
        "auth",
        "jwt",
        "code",
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
    _URL_QUERY_RE 覆盖）。逐参数判定，非敏感 key 原样保留，首尾空白保持原样。
    """
    if not text or "\n" in text or "&" not in text:
        return text
    stripped = text.strip()
    if not _FORM_BODY_RE.match(stripped):
        return text
    prefix, suffix = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
    parts: list[str] = []
    for pair in stripped.split("&"):
        key, sep, value = pair.partition("=")
        if key.lower() in _SENSITIVE_BODY_KEYS:
            parts.append(f"{key}{sep}{_mask_token(value)}")
        else:
            parts.append(pair)
    return f"{prefix}{'&'.join(parts)}{suffix}"


# 程序化 env 引用（`os.getenv('X')` / `os.environ[...]` / `process.env.X` / `$ENV{X}`）
# 是变量名引用而非凭据值——掩码会破坏代码示例的可读性（对齐 Hermes 的 guard）。
_ENV_LOOKUP_VALUE_RE = re.compile(
    r"^(?:os\.(?:getenv|environ)|process\.env|\$ENV\{)",
)

# 已掩码形态（`***` 或 `xxxxxx...xxxx`）：双重匹配的正则（ENV_LOWER 与 ENV 重叠的
# `client_secret=`、ENV 与 CLI 重叠的 `--password=`）二次 `_mask_token` 会把可读的
# `mysecr...5678` 折叠成 `***`，这里识别并保持。明文 secret 含 `...` 中段或
# 恰好 6+3+4 字符形态的概率可忽略（API token 字符集不含 `...`）。
_MASKED_VALUE_RE = re.compile(r"^(?:\*{3}|[^\"']{6}\.{3}[^\"']{4})$")

_JSON_KEY_NAMES = (
    r"(?:api_?[Kk]ey|token|secret|password|access_token|"
    r"refresh_token|auth_token|bearer|secret_value|raw_secret|secret_input|key_material)"
)
# JSON 字符串值支持 `\"` 转义引号（`{"password": "my\"secret"}` 整体捕获不截断）。
_JSON_FIELD_RE = re.compile(rf'("{_JSON_KEY_NAMES}")\s*:\s*"((?:[^"\\\\]|\\.)*)"', re.IGNORECASE)

_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:]+:)([^@]+)(@)", re.IGNORECASE
)

# ── URL Query parameters (OPT-2) ────────────────────────────────
# key=value 分组捕获，替换仅作用于 value，避免 value 是 key 名字符子串时
# `.replace()` 连带破坏 key 名（`?api_key=a` 误伤为 `?***pi_key=***`）。
# key 名单必须 ⊇ _SECRET_ENV_NAMES（ENV 正则加负向后顾后不再兜底 URL 参数，
# 若名单不一致，`?credential=`/`?auth=` 会双双落空而明文泄漏）。
# 追加下划线边界短名（`?openai_key=`/`?db_pw=`/`?FAL_KEY=`）——URL 中同样存在
# 小写短名凭据参数，与 _ENV_ASSIGN_LOWER_RE 的短名集合保持一致；前缀限长 `{1,64}`
# 与 _ENV_ASSIGN_LOWER_RE 一致，避免无界回溯。
# `x-api-key`/`api-key` 等连字符形式必须显式列出——`api[-_.]?key` 从 `?` 后锚定
# 无法覆盖带 `x-` 前缀的 key，且与 _SECRET_HEADER_NAMES 的 header 名单对齐
# （header 覆盖了 query 却漏掉即造成明文泄漏）。
# 与 Hermes _SENSITIVE_QUERY_PARAMS（redact.py:27-44）对齐：`code`（OAuth 授权码）/
# `signature`（预签名 URL 签名）/`x-amz-signature`（AWS S3 预签名）/`session`（会话
# 凭据）均为明文即可盗用的敏感参数。IGNORECASE 下 `X-Amz-Signature` 亦命中。
# `_SECRET_ENV_NAMES` 带 `[A-Z0-9_]{0,64}` 后缀对齐 _ENV_ASSIGN_RE 的前后缀设计——
# `?TOKEN_LEGACY=`/`?API_KEY_OLD=` 等续接名由 _URL_QUERY_RE 精确脱敏；
# 短名部分带 `[a-z0-9_]{0,64}` 后缀与 _ENV_ASSIGN_LOWER_RE 保持一致
# （`?openai_key_legacy=`），避免依赖 ENV 正则的错位匹配。
_URL_QUERY_KEYS = rf"{_SECRET_ENV_NAMES}[A-Z0-9_]{{0,64}}|access_token|code|signature|x-amz-signature|session|jwt|key|x-api-key|x-goog-api-key|x-api-token|x-auth-token|x-access-token|api[-_.]?key|[a-z0-9_]{{1,64}}_(?:key|pass|pw|token|secret|password|passwd|credential|auth)[a-z0-9_]{{0,64}}"
_URL_QUERY_RE = re.compile(rf"([?&](?:{_URL_QUERY_KEYS})=)([^&\s]+)", re.IGNORECASE)

# ── CLI flags (OPT-5) ───────────────────────────────────────────
# flag 名、分隔符（空格或 `=`）、值分组捕获，替换仅作用于值，避免短值误伤 flag 名
# （`--secret s` 误伤为 `--***ecret ***`）。支持 `--api-key=xxx`（等号分隔，CLI
# 高频形式）与 `--api-key xxx`（空格分隔）；`--password=`/`--token=` 亦由
# _ENV_ASSIGN_RE 覆盖（幂等）。
_CLI_FLAG_RE = re.compile(
    r"(--(?:api[-_]?key|hook[-_]?token|token|secret|password|passwd)(?:\s+|=))((?:(['\"])(?:[^'\"\\\\]|''|\\.)*\3)|(?:[^\s\"']+))",
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
_SECRET_HEADER_NAMES = r"(?:x-api-key|x-goog-api-key|api-key|apikey|x-api-token|x-auth-token|x-access-token)"
_SECRET_HEADER_RE = re.compile(rf"({_SECRET_HEADER_NAMES}\s*:\s*)(\S+)", re.IGNORECASE)

# ── JWT token (对齐 Hermes _JWT_RE) ──────────────────────────────
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")

# ── 控制字符拆分 token 防护 (对齐 Hermes issue #77484) ─────────
# 控制/零宽字符（ESC、零宽空格、换行等）可拆分 token body，使 _PREFIX_RE 无法
# 连续匹配 —— `sk-abc\x1bdef…` 凭据因此绕过脱敏泄漏。策略：剥离控制字符后
# 匹配，再映射回原文对应 span 掩码；仅当 span 内全部为 token-body 或控制
# 字符时才掩码，避免跨行误伤无关文本。
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u2028-\u202f\u2060\ufeff]")
_TOKEN_BODY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.")


def _mask_token(token: str) -> str:
    """Mask a token: fully hide short ones, preserve head/tail for long ones."""
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _redact_value(name: str, value: str) -> str | None:
    """Mask a secret value under a secret ``name``, or return None to keep original.

    Programmatic lookups (``os.getenv('X')``) and prose keys (``author=Smith``)
    are kept intact. Quoted values (``KEY="secret"``, including values with
    spaces) preserve their quotes. Shared by ENV / YAML / CLI replacers.

    Values already in masked shape (``***`` or ``xxxxxx...xxxx``) are left
    untouched: `_ENV_ASSIGN_RE` / `_ENV_ASSIGN_LOWER_RE` / `_CLI_FLAG_RE`
    overlap on keys like `client_secret=...` / `--password=...`, and re-masking
    the short masked tail would collapse readable `xxxxxx...xxxx` into `***`.
    """
    if value[:1] in "\"'" and value[-1:] == value[:1]:
        inner, quote = value[1:-1], value[0]
    else:
        inner, quote = value, ""
    if _ENV_LOOKUP_VALUE_RE.match(inner):
        return None
    if _MASKED_VALUE_RE.match(inner):
        return None
    if not _key_has_secret_keyword(name):
        return None
    return f"{quote}{_mask_token(inner)}{quote}"


def _redact_env_assignment(m: re.Match[str]) -> str:
    """Replacement for _ENV_ASSIGN_RE / _ENV_ASSIGN_LOWER_RE."""
    name, value = m.group(1), m.group(2)
    masked = _redact_value(name, value)
    return f"{name}={masked}" if masked is not None else m.group(0)


def _redact_yaml_assignment(m: re.Match[str]) -> str:
    """Replacement for _YAML_ASSIGN_RE (unquoted & quoted values)."""
    key, sep, value = m.group(1), m.group(2), m.group(3)
    masked = _redact_value(key, value)
    return f"{key}{sep}{masked}" if masked is not None else m.group(0)


def _redact_cli_flag(m: re.Match[str]) -> str:
    """Replacement for _CLI_FLAG_RE (unquoted & quoted values)."""
    flag, value = m.group(1), m.group(2)
    masked = _redact_value(flag, value)
    return f"{flag}{masked}" if masked is not None else m.group(0)
