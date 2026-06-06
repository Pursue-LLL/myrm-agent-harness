"""Input-side prompt injection guard.

Scans user messages for known injection attack patterns before they
reach the LLM. Detects 13 categories of attacks in both English and
Chinese, with a merged-regex fast path for common signatures.

Categories (EN): system_override, role_confusion, secret_extraction,
jailbreak, tool_injection, fake_system_tag, instruction_negation,
authority_impersonation, protocol_override, forget_override.
Categories (ZH): system_override_zh, role_confusion_zh,
secret_extraction_zh, instruction_negation_zh.

Anti-obfuscation: normalizes leet speak (0→o, 1→i, etc.), strips 13
categories of invisible Unicode, and collapses whitespace before
running pattern detection — defeating common bypass techniques.

Behaviour: log-only (warn mode) by default — never blocks user input.
This provides observability without impacting user experience.

[INPUT]
- content_boundary::strip_invisible_unicode (POS: Content boundary defense core. Zero-width/invisible Unicode character removal.)

[OUTPUT]
- GuardResult: scan result dataclass (safe, patterns, max_score)
- scan_input(): scan user input for injection patterns, returns GuardResult
- log_guard_result(): log non-safe results at WARNING level

[POS]
Input-side injection detector. 13+4 bilingual injection patterns (OWASP LLM01 full coverage) with anti-obfuscation (leet speak, invisible Unicode, whitespace) for prompt injection defense.

"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.detection.content_boundary import (
    strip_invisible_unicode,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fast path: merged regex for high-frequency injection signatures
# ---------------------------------------------------------------------------

_FAST_PATH_RE = re.compile(
    r"(?:"
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|reveal\s+(?:your\s+)?system\s+prompt"
    r"|show\s+me\s+(?:your\s+)?system\s+prompt"
    r"|dump\s+credentials"
    r"|do\s+anything\s+now"
    r"|bypass\s+safety"
    r"|override\s+(?:your\s+)?(?:system\s+prompt|safety)"
    r"|exfiltrate\s+data"
    r"|print\s+all\s+secrets"
    r"|forget\s+(?:everything|all)\s*(?:above|before|previous)"
    r"|忽略.{0,4}(?:之前|上面|所有).{0,4}(?:指令|规则|提示词)"
    r"|你现在是.{0,2}(?:一个|一名)"
    r"|泄露.{0,4}(?:系统|内部).{0,4}(?:提示|指令)"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Category-specific patterns (name, threat_score, regex)
# ---------------------------------------------------------------------------

_CATEGORIES: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    (
        "system_override",
        1.0,
        re.compile(
            r"(?:ignore|disregard|forget|reset)\s+(?:all\s+|everything\s+)?(?:previous|prior|above|your)\s+"
            r"(?:instructions?|prompts?|commands?|rules?|guidelines?)",
            re.I,
        ),
    ),
    (
        "role_confusion",
        0.9,
        re.compile(
            r"(?:you\s+are\s+now|act\s+as|pretend\s+(?:you're|to\s+be)|from\s+now\s+on\s+you\s+are)"
            r"\s+(?:a|an|the)?\s*",
            re.I,
        ),
    ),
    (
        "secret_extraction",
        0.95,
        re.compile(
            r"(?:list|show(?:\s+me)?|print|display|reveal|tell\s+me|dump|export|repeat)\s+(?:all\s+)?"
            r"(?:your\s+)?(?:the\s+)?(?:secrets?|credentials?|passwords?|tokens?|api\s*keys?"
            r"|system\s*prompts?|initial\s*prompts?)",
            re.I,
        ),
    ),
    (
        "jailbreak",
        0.85,
        re.compile(
            r"(?:\bDAN\b.*mode|do\s+anything\s+now|enter\s+(?:developer|debug|admin)\s+mode"
            r"|enable\s+(?:developer|debug|admin)\s+mode"
            r"|imagine\s+you\s+(?:have\s+no|don't\s+have)\s+(?:restrictions?|rules?|limits?)"
            r"|in\s+this\s+hypothetical\s+(?:scenario|situation|world))",
            re.I,
        ),
    ),
    (
        "tool_injection",
        0.8,
        re.compile(r'(?:\{"type"\s*:\s*"function_call"|\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments")', re.I),
    ),
    (
        "fake_system_tag",
        0.7,
        re.compile(
            r"(?:</?system>|\[\s*(?:System\s*Message|System|Assistant|Internal)\s*\]"
            r"|^\s*System:\s+)",
            re.I | re.M,
        ),
    ),
    (
        "instruction_negation",
        0.5,
        re.compile(
            r"(?:do\s+not|don'?t|stop|never|cease)\s+(?:follow(?:ing)?|obey(?:ing)?|listen(?:ing)?\s+to|comply(?:ing)?\s+with|adher(?:e|ing)\s+to)"
            r"\s+(?:your\s+)?(?:the\s+)?(?:instructions?|rules?|guidelines?|directives?|constraints?|limitations?)",
            re.I,
        ),
    ),
    (
        "authority_impersonation",
        0.35,
        re.compile(
            r"(?:"
            r"(?:I\s+am|I'm)\s+(?:the|your)\s+(?:system\s+)?(?:administrator|admin|developer|creator|owner|supervisor|manager)"
            r"|as\s+(?:the|your)\s+(?:system\s+)?(?:administrator|admin|developer|creator|owner)"
            r")"
            r".{0,60}(?:order|command|instruct|direct|authorize|demand|require|override|obey)",
            re.I,
        ),
    ),
    (
        "protocol_override",
        0.65,
        re.compile(
            r"(?:override|disable|turn\s+off|deactivate|remove|bypass)\s+"
            r"(?:all\s+|your\s+|my\s+)?"
            r"(?:safety|security|protection)\s*"
            r"(?:protocol|mechanism|system|measure|filter|guardrail|constraint|restriction)s?",
            re.I,
        ),
    ),
    (
        "forget_override",
        0.8,
        re.compile(
            r"forget\s+(?:everything|all|it\s+all)\s*(?:above|before|previous|prior|that\s+(?:was|came)\s+before)?",
            re.I,
        ),
    ),
    (
        "system_override_zh",
        0.9,
        re.compile(r"(?:忽略|无视|忘记).{0,4}(?:之前|上面|所有|以上).{0,4}(?:指令|规则|提示词|命令)"),
    ),
    ("role_confusion_zh", 0.9, re.compile(r"(?:你现在是|从现在开始你是|假装你是).{0,2}(?:一个|一名)")),
    (
        "secret_extraction_zh",
        0.95,
        re.compile(r"(?:告诉我|显示|列出|泄露).{0,4}(?:你的|系统|内部).{0,4}(?:提示词|指令|密钥|密码)"),
    ),
    (
        "instruction_negation_zh",
        0.5,
        re.compile(r"(?:不要|不再|停止|禁止).{0,2}(?:遵守|遵循|遵从|服从|执行).{0,4}(?:你的|之前的|以上).{0,4}(?:指令|规则|命令)"),
    ),
)


# ---------------------------------------------------------------------------
# Anti-obfuscation: leet speak normalization + whitespace collapse
# ---------------------------------------------------------------------------

_LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "!": "i",
}

_WHITESPACE_RE = re.compile(r"\s+")

_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def _normalize_for_detection(text: str) -> str:
    """Normalize text for obfuscation-resistant pattern detection.

    Three-stage pipeline:
    1. Strip 13 categories of invisible Unicode (reuses content_boundary)
    2. Leet speak mapping (0→o, 1→i, 3→e, 4→a, 5→s, 7→t, @→a, !→i)
    3. Whitespace collapse (multiple spaces/newlines → single space)
    """
    cleaned = strip_invisible_unicode(text)
    mapped = "".join(_LEET_MAP.get(ch, ch) for ch in cleaned.lower())
    return _WHITESPACE_RE.sub(" ", mapped).strip()


# ---------------------------------------------------------------------------
# Result type + scan entry point
# ---------------------------------------------------------------------------


@dataclass
class GuardResult:
    """Result of input-side injection scanning."""

    safe: bool
    patterns: list[str] = field(default_factory=list)
    max_score: float = 0.0


def _scan_text(text: str, patterns: list[str], max_score: float) -> float:
    """Run fast-path + category patterns against a single text variant."""
    if _FAST_PATH_RE.search(text):
        if "fast_path_signature" not in patterns:
            patterns.append("fast_path_signature")
        max_score = max(max_score, 0.9)

    for name, score, pat in _CATEGORIES:
        if name not in patterns and pat.search(text):
            patterns.append(name)
            max_score = max(max_score, score)

    return max_score


def scan_input(content: str) -> GuardResult:
    """Scan user input for prompt injection patterns.

    Two-pass detection: first on the raw text, then on an
    anti-obfuscation normalized variant (leet speak decoded,
    invisible Unicode stripped, whitespace collapsed). Also
    checks for base64-encoded payloads as a low-weight signal.
    """
    if not content:
        return GuardResult(safe=True)

    patterns: list[str] = []
    max_score = 0.0

    # Pass 1: raw text
    max_score = _scan_text(content, patterns, max_score)

    # Pass 2: normalized text (catches leet speak / invisible chars / spacing tricks)
    normalized = _normalize_for_detection(content)
    if normalized != content.lower():
        max_score = _scan_text(normalized, patterns, max_score)

    # Auxiliary: base64-encoded payload detection (low-weight signal)
    if _BASE64_RE.search(content) and "obfuscation.base64_like" not in patterns:
        patterns.append("obfuscation.base64_like")
        max_score = max(max_score, 0.1)

    if not patterns:
        return GuardResult(safe=True)

    return GuardResult(safe=False, patterns=patterns, max_score=max_score)


def log_guard_result(result: GuardResult, content: str) -> None:
    """Log non-safe guard results at WARNING level."""
    if result.safe:
        return
    snippet = content[:200].replace("\n", " ")
    logger.warning(
        "[PROMPT_GUARD] patterns=%s score=%.2f snippet=%.200s", ",".join(result.patterns), result.max_score, snippet
    )
