"""Credential leak detector for outbound content.

Scans model output for potential credential leaks before delivery,
preventing accidental exfiltration of API keys, tokens, passwords,
and other sensitive values.

Detection strategy:
  1. Prefix-based API key patterns (30+ cloud providers)
  2. Context-aware patterns (ENV assignments, JSON fields, Auth headers)
  3. Structural formats (JWT, PEM block-level, database URLs, blockchain, cloud infra)
  4. Shannon entropy analysis (catches unknown credential formats; see entropy_scan)
  5. Context-aware blockchain patterns (mnemonic seed phrases)

Smart redaction preserves first 6 / last 4 characters of long tokens
for debugging while keeping the credential unusable. PEM blocks are
fully redacted (BEGIN to END) with type label preserved.

[INPUT]
- core.security.detection.secret_value::is_reference_value (POS: shared rules telling a secret from a reference to
  one: templates, identifiers, calls, class names, slugs, domains, query strings.)
- core.security.detection.entropy_scan::scan_high_entropy (POS: unknown-credential tier of the leak detector.)

[OUTPUT]
- DISTINCTIVE_KEY_PATTERNS: the vendor-prefix shapes that identify a key on their own (name, pattern), for a caller that
  refuses a message on a hit
- scan_for_leaks(): detect credential patterns, returns matched pattern names
- redact_leaks(): smart-redact credentials with partial visibility
- log_leaks(): log leak detections at WARNING level

[POS]
Output-side credential leak detector. 40+ credential pattern matchers (API key prefixes + blockchain + cloud infra + ENV/JSON/Header context + Shannon entropy + PEM block-level multiline redaction) for preventing secret exfiltration.

"""

from __future__ import annotations

import logging
import re
from functools import partial

from myrm_agent_harness.core.security.detection.entropy_scan import scan_high_entropy
from myrm_agent_harness.core.security.detection.secret_value import is_reference_value

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Prefix-based API key patterns (structurally identifiable)
# ---------------------------------------------------------------------------
_API_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Payment
    ("stripe_key", re.compile(r"sk_(?:live|test)_[a-zA-Z0-9]{24,}")),
    ("stripe_restricted", re.compile(r"rk_(?:live|test)_[a-zA-Z0-9]{24,}")),
    # AI / LLM
    ("openai_key", re.compile(r"sk-[a-zA-Z0-9_-]{48,}")),
    ("anthropic_key", re.compile(r"sk-ant-[a-zA-Z0-9_-]{32,}")),
    ("google_key", re.compile(r"AIza[a-zA-Z0-9_-]{35}")),
    ("huggingface_token", re.compile(r"hf_[a-zA-Z0-9]{34,}")),
    ("replicate_token", re.compile(r"r8_[a-zA-Z0-9]{36,}")),
    ("perplexity_key", re.compile(r"pplx-[a-zA-Z0-9]{48,}")),
    ("groq_key", re.compile(r"gsk_[a-zA-Z0-9]{40,}")),
    ("databricks_token", re.compile(r"dapi[a-f0-9]{32}")),
    # Cloud
    ("aws_access_key", re.compile(r"AKIA[A-Z0-9]{16}")),
    ("aws_session_token", re.compile(r"ASIA[A-Z0-9]{16}")),
    ("digitalocean_token", re.compile(r"dop_v1_[a-f0-9]{64}")),
    ("vercel_token", re.compile(r"vercel_[a-zA-Z0-9_-]{24,}")),
    ("supabase_key", re.compile(r"sbp_[a-f0-9]{40,}")),
    ("cloudflare_token", re.compile(r"cf_[a-zA-Z0-9_-]{37,}")),
    # DevOps / VCS
    ("github_token", re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}")),
    ("github_pat", re.compile(r"github_pat_[a-zA-Z0-9_]{22,}")),
    ("gitlab_token", re.compile(r"glpat-[a-zA-Z0-9_-]{20,}")),
    ("npm_token", re.compile(r"npm_[a-zA-Z0-9]{36,}")),
    ("pypi_token", re.compile(r"pypi-[a-zA-Z0-9_-]{36,}")),
    # Communication
    ("slack_token", re.compile(r"xox[bpras]-[a-zA-Z0-9-]{10,}")),
    ("telegram_bot", re.compile(r"\d{8,10}:[a-zA-Z0-9_-]{35}")),
    ("sendgrid_key", re.compile(r"SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}")),
    ("twilio_key", re.compile(r"SK[a-f0-9]{32}")),
    # Media / AI services
    ("elevenlabs_key", re.compile(r"el_[a-zA-Z0-9]{32,}")),
    ("fal_key", re.compile(r"fal_[a-zA-Z0-9_-]{32,}")),
    # Search / Web
    ("tavily_key", re.compile(r"tvly-[a-zA-Z0-9]{32,}")),
    ("firecrawl_key", re.compile(r"fc-[a-zA-Z0-9]{32,}")),
    ("browserbase_key", re.compile(r"bb_live_[a-zA-Z0-9]{32,}")),
    # Messaging / E-commerce
    (
        "discord_bot_token",
        re.compile(r"[MN][A-Za-z\d]{14,28}\.[A-Za-z\d_-]{4,7}\.[A-Za-z\d_-]{25,}"),
    ),
    ("shopify_token", re.compile(r"shpat_[a-fA-F0-9]{32}")),
    ("shopify_shared_secret", re.compile(r"shpss_[a-fA-F0-9]{32}")),
)

# Shapes that also occur in ordinary text, so masking them is harmless but refusing a message on them is not: a prefix of
# two or three characters, a plain hex or digit body (a hash, a build id, a bot id), or a lowercase word followed by a
# body that may hold ``_`` and ``-`` (an identifier such as ``vercel_request_handler_name``).
_WEAK_PREFIX_KEY_NAMES: frozenset[str] = frozenset(
    {
        "telegram_bot",
        "discord_bot_token",
        "twilio_key",
        "databricks_token",
        "cloudflare_token",
        "elevenlabs_key",
        "firecrawl_key",
        "vercel_token",
        "fal_key",
    }
)

# The shapes a vendor prefix identifies on its own: what a caller that refuses a message on a hit (a precision-first
# gate) reads, so the gate learns each vendor added to the table above without keeping a list of its own. A caller joins
# the patterns into one alternation, so each is flag-free and has no group.
DISTINCTIVE_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, pattern) for name, pattern in _API_KEY_PATTERNS if name not in _WEAK_PREFIX_KEY_NAMES
)

# ---------------------------------------------------------------------------
# 2. Structural format patterns
# ---------------------------------------------------------------------------

# Multiline PEM block pattern: matches entire BEGIN...END block including content
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"[\s\S]*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)

_STRUCTURAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("jwt_token", re.compile(r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]+")),
    (
        "pem_private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "database_url",
        re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis(?:s)?|amqps?)://[^:]+:[^@]+@[^\s]+"),
    ),
    # Blockchain
    ("ethereum_address", re.compile(r"\b0x[a-fA-F0-9]{40}\b")),
    # Cloud infrastructure
    (
        "azure_storage_key",
        re.compile(r"DefaultEndpointsProtocol=https;AccountName=[a-z0-9]+;AccountKey=[A-Za-z0-9+/=]{88};"),
    ),
    (
        "discord_webhook",
        re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d{17,19}/[A-Za-z0-9_\-]{68}"),
    ),
)

# ---------------------------------------------------------------------------
# 3. Context-aware patterns (ENV assignments, JSON fields, Auth headers)
# ---------------------------------------------------------------------------
_PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-].*|xxx+|placeholder|example|changeme|TODO|CHANGE_ME|INSERT_HERE|"
    r"<[^>]+>|\$\{[^}]+\}|%\([^)]+\)s|None|null|undefined|test|demo|fake|dummy|sample|"
    # an earlier redaction (see _smart_redact_value, or the PII redactor's "[REDACTED] [PII:password]"): scanning
    # redacted text again must not redact it again
    r"\[REDACTED(?::[^\]]*)?\](?: \[PII:[a-z_]+\])?|.{6}\*\*\*\.\.\..{4}(?: \[REDACTED:[^\]]*\])?)$",
    re.IGNORECASE,
)

_SENSITIVE_KEY_RE = (
    r"(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|AUTH[_-]?TOKEN|"
    r"PRIVATE[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|PASSPHRASE|"
    r"APP[_-]?SECRET|CLIENT[_-]?SECRET|SIGNING[_-]?KEY|ENCRYPTION[_-]?KEY)"
)

_MIN_CONTEXT_VALUE_LENGTH = 16

_ENV_PATTERN = re.compile(
    rf"(?:^|[\s;])(?:export\s+)?(?P<key>\w*{_SENSITIVE_KEY_RE})\s*=\s*['\"]?(?P<value>[^\s'\"#;]+)",
    re.MULTILINE | re.IGNORECASE,
)

_JSON_PATTERN = re.compile(
    rf"""["'](?P<key>(?P<prefix>[\w.-]*?){_SENSITIVE_KEY_RE})["']\s*:\s*["'](?P<value>[^"']{{16,}})["']""",
    re.IGNORECASE,
)

_LABELED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("env_credential", _ENV_PATTERN),
    ("json_credential", _JSON_PATTERN),
)

# The word before a bare `Token` that makes its value a paging handle (`nextToken`, `NextContinuationToken`).
_PAGING_WORD_RE = re.compile(
    r"next|prev(?:ious)?|pag(?:e|ing|ination)|continu(?:ation|e)|cursor|sync|resume|start(?:ing)?", re.IGNORECASE
)
_KEY_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

_AUTH_HEADER_PATTERN = re.compile(r"Authorization:\s*(?:Bearer|Basic|Token)\s+([a-zA-Z0-9_./+=-]{20,})", re.IGNORECASE)


_MNEMONIC_PATTERN = re.compile(
    r"(?:mnemonic|seed|recovery)\s*(?:phrase|words?)?\s*[=:]\s*['\"]?"
    r"((?:[a-z]{3,8}\s+){11,23}[a-z]{3,8})"
    r"['\"]?",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value.strip()))


def _is_ui_string_or_paging_handle(prefix: str, key: str, value: str) -> bool:
    """Whether a value under a prefixed JSON key (`voiceAuthToken`, `nextToken`) is no credential.

    A prefixed key names a UI string or a paging handle as often as a credential. A UI string has spaces or non-ASCII
    text. A paging handle is a bare `Token` right after a paging word (`NextContinuationToken`, `next_token`) and is
    passed back verbatim, so masking it breaks paging; `nextAuthToken` and `pageAccessToken` are credentials.
    """
    if not value.isascii() or any(c.isspace() for c in value):
        return True
    words = _KEY_WORD_RE.findall(prefix)
    return key[len(prefix) :].lower() == "token" and bool(words) and _PAGING_WORD_RE.fullmatch(words[-1]) is not None


def _credential_value(m: re.Match[str]) -> str | None:
    """The credential of an ENV assignment or JSON field, or None for a short value, a placeholder, a reference to a
    secret, or (under a prefixed JSON key) a UI string or paging handle. A bare key (`token`) keeps a spaced value
    (`Bearer <token>`).
    """
    value = m.group("value")
    if len(value) < _MIN_CONTEXT_VALUE_LENGTH or _is_placeholder(value):
        return None
    prefix = m.groupdict().get("prefix")  # only a JSON key captures one
    if prefix and _is_ui_string_or_paging_handle(prefix, m.group("key"), value):
        return None
    return None if is_reference_value(value, key=m.group("key")) else value


def _scan_context_patterns(content: str) -> list[str]:
    """Detect credentials in ENV assignments, JSON fields, Auth headers, and mnemonic phrases."""
    found = [name for name, pat in _LABELED_PATTERNS if any(_credential_value(m) for m in pat.finditer(content))]

    if _AUTH_HEADER_PATTERN.search(content):
        found.append("auth_header_credential")

    if _MNEMONIC_PATTERN.search(content):
        found.append("mnemonic_phrase")

    return found


# ---------------------------------------------------------------------------
# Combined pattern list (prefix + structural)
# ---------------------------------------------------------------------------
_ALL_PREFIX_STRUCTURAL: tuple[tuple[str, re.Pattern[str]], ...] = _API_KEY_PATTERNS + _STRUCTURAL_PATTERNS

# ---------------------------------------------------------------------------
# Smart redaction helpers
# ---------------------------------------------------------------------------
_SMART_REDACT_THRESHOLD = 18


def _redact_pem_block(m: re.Match[str]) -> str:
    """Replace an entire PEM block with a redacted placeholder.

    Preserves the key type identifier (RSA/EC/OPENSSH) for debugging
    context while fully redacting the key content including markers.
    """
    full = m.group(0)
    begin_line = full.split("\n", 1)[0]
    # Extract key type from BEGIN marker for the label
    type_match = re.search(r"-----BEGIN ((?:RSA |EC |OPENSSH )?)PRIVATE KEY-----", begin_line)
    key_type = type_match.group(1).strip() if type_match else ""
    type_label = f":{key_type}" if key_type else ""
    return f"[REDACTED:pem_private_key_block{type_label}]"


def _smart_redact_value(name: str, value: str) -> str:
    """Build a smart-redacted replacement string.

    Short values (<18 chars) are fully masked.
    Long values preserve first 6 / last 4 characters for debugging.
    """
    if len(value) < _SMART_REDACT_THRESHOLD:
        return f"[REDACTED:{name}]"
    return f"{value[:6]}***...{value[-4:]} [REDACTED:{name}]"


def _smart_redact_match(name: str, match: re.Match[str]) -> str:
    return _smart_redact_value(name, match.group(0))


def _redact_labeled_match(name: str, m: re.Match[str]) -> str:
    val = _credential_value(m)
    if val is None:
        return m.group(0)
    # Cut by position: the key may contain the value's text, so a text replace could mask the key instead.
    return m.string[m.start() : m.start("value")] + _smart_redact_value(name, val) + m.string[m.end("value") : m.end()]


def _redact_auth_match(m: re.Match[str]) -> str:
    val = m.group(1)
    return m.group(0).replace(val, _smart_redact_value("auth_header_credential", val), 1)


def _redact_mnemonic_match(m: re.Match[str]) -> str:
    val = m.group(1)
    return m.group(0).replace(val, "[REDACTED:mnemonic_phrase]", 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _collect_prefix_matches(content: str) -> set[str]:
    """Collect all tokens matched by prefix/structural patterns."""
    matched: set[str] = set()
    for _, pat in _ALL_PREFIX_STRUCTURAL:
        for m in pat.finditer(content):
            matched.add(m.group(0))
    return matched


def scan_for_leaks(content: str) -> list[str]:
    """Scan content for credential patterns.

    Returns a list of matched pattern names. Empty list means clean.
    This is a pure function — no logging, no side effects.
    """
    if not content:
        return []
    matches = [name for name, pat in _ALL_PREFIX_STRUCTURAL if pat.search(content)]
    matches.extend(_scan_context_patterns(content))

    entropy_hits = scan_high_entropy(content, _collect_prefix_matches(content))
    if entropy_hits:
        matches.append("high_entropy_token")

    return matches


def redact_leaks(content: str) -> str:
    """Smart-redact detected credentials.

    Short tokens are fully masked; long tokens preserve first 6 / last 4
    characters for debugging. Each replacement includes the pattern name.

    Safe to call on any text — returns unchanged if nothing is found.
    """
    if not content:
        return content
    result = content

    # PEM blocks must be redacted first (before per-line pattern matching)
    # to prevent partial leakage of base64 key content lines.
    result = _PEM_BLOCK_RE.sub(_redact_pem_block, result)

    for name, pat in _ALL_PREFIX_STRUCTURAL:
        result = pat.sub(partial(_smart_redact_match, name), result)

    for name, pat in _LABELED_PATTERNS:
        result = pat.sub(partial(_redact_labeled_match, name), result)
    result = _AUTH_HEADER_PATTERN.sub(_redact_auth_match, result)
    result = _MNEMONIC_PATTERN.sub(_redact_mnemonic_match, result)

    for _, token in scan_high_entropy(content, _collect_prefix_matches(content)):
        result = result.replace(token, _smart_redact_value("high_entropy_token", token), 1)

    return result


def log_leaks(matches: list[str], content: str) -> None:
    """Log credential leak detections at WARNING level."""
    snippet = content[:200].replace("\n", " ")
    logger.warning("[CREDENTIAL_LEAK] patterns=%s snippet=%.200s", ",".join(matches), snippet)
