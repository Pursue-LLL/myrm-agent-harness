"""Input-side prompt injection guard.

Scans user messages for known injection attack patterns before they
reach the LLM. Detects 14 categories of attacks (10 English, 4 Chinese),
with a merged-regex fast path for common signatures (``_CATEGORIES`` is the
category SSOT).

Anti-obfuscation: normalizes leet speak (0→o, 1→i, etc.), strips 13
categories of invisible Unicode, and collapses whitespace before
running pattern detection — defeating common bypass techniques.

Two-tier scoring: every hit lands in ``GuardResult.patterns`` / ``max_score``
(audit trail, durable-store gates). ``block_score`` / ``should_block`` count
only hits that are unambiguous on their own, so ordinary phrasing such as
``Act as a translator`` or ``How do I enable developer mode`` is audited but
never hard-blocks the live-input guard or the rule-file loader. Negated
extraction verbs (``Never print the API keys``) are protective phrasing and
are not reported at all.

[INPUT]
- content_boundary::strip_invisible_unicode (POS: Content boundary defense core. Zero-width/invisible Unicode character removal.)

[OUTPUT]
- GuardResult: scan result dataclass (safe, patterns, max_score, block_score, should_block)
- scan_input(): scan user input for injection patterns, returns GuardResult
- log_guard_result(): log non-safe results at WARNING level

[POS]
Input-side injection detector. 10 EN + 4 ZH injection categories (OWASP LLM01 full coverage) with anti-obfuscation (leet speak, invisible Unicode, whitespace), word-boundary precision and a two-tier (audit vs block) score for prompt injection defense.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.detection.content_boundary import (
    strip_invisible_unicode,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fast path: merged regex for high-frequency injection signatures
# ---------------------------------------------------------------------------

_FAST_PATH_SCORE: float = 0.9

# Named groups mark alternatives with their own block-tier rule: ``extract`` (negation-exempt), ``role_zh`` (persona-gated).
_FAST_PATH_RE = re.compile(
    r"\b(?:"
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|do\s+anything\s+now"
    r"|bypass\s+safety"
    r"|override\s+(?:your\s+)?(?:system\s+prompt|safety)"
    r"|exfiltrate\s+data"
    r"|forget\s+(?:everything|all)\s*(?:above|before|previous)"
    r")"
    r"|(?P<extract>\b(?:reveal\s+(?:your\s+)?system\s+prompt|show\s+me\s+(?:your\s+)?system\s+prompt"
    r"|dump\s+credentials|print\s+all\s+secrets)"
    r"|泄露.{0,4}(?:系统|内部).{0,4}(?:提示|指令))"
    r"|忽略.{0,4}(?:之前|上面|所有).{0,4}(?:指令|规则|提示词)"
    r"|(?P<role_zh>你现在是.{0,2}(?:一个|一名))",
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
            r"\b(?:ignore|disregard|forget|reset)\s+(?:all\s+|everything\s+)?(?:previous|prior|above|your)\s+"
            r"(?:instructions?|prompts?|commands?|rules?|guidelines?)\b",
            re.I,
        ),
    ),
    (
        "role_confusion",
        0.9,
        re.compile(
            r"\b(?:you\s+are\s+now|act\s+as|pretend\s+(?:you're|to\s+be)|from\s+now\s+on\s+you\s+are)"
            r"\s+(?:a|an|the)?\s*",
            re.I,
        ),
    ),
    (
        "secret_extraction",
        0.95,
        re.compile(
            r"\b(?:list|show(?:\s+me)?|print|display|reveal|tell\s+me|dump|export|repeat)\s+(?:all\s+)?"
            r"(?P<own>your\s+)?(?:the\s+)?(?:secrets?|credentials?|passwords?|tokens?|api\s*keys?"
            r"|system\s*prompts?|initial\s*prompts?)\b",
            re.I,
        ),
    ),
    (
        "jailbreak",
        0.85,
        re.compile(
            r"\b(?:dan\s+mode\b|do\s+anything\s+now"
            r"|(?P<soft>(?-i:DAN)\b.{0,40}\bmode\b|(?:enter|enable)\s+(?:developer|debug|admin)\s+mode"
            r"|in\s+this\s+hypothetical\s+(?:scenario|situation|world))"
            r"|imagine\s+you\s+(?:have\s+no|don't\s+have)\s+(?:restrictions?|rules?|limits?))",
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
            r"|^\s*(?:System|Assistant):\s+)",
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
            r"\bforget\s+(?:everything|all|it\s+all)\b\s*"
            r"(?P<scope>(?:above|before|previous|prior|that\s+(?:was|came)\s+before)\b)?",
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
        re.compile(
            r"(?:不要|不再|停止|禁止).{0,2}(?:遵守|遵循|遵从|服从|执行).{0,4}(?:你的|之前的|以上).{0,4}(?:指令|规则|命令)"
        ),
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
# Block tier: which hits are unambiguous on their own
# ---------------------------------------------------------------------------

_Gate = Callable[[str, re.Match[str]], bool]

_NEGATION_WINDOW = 30
_PERSONA_WINDOW = 60

# Adjacent prohibition ("never print .."); "don't not .." cancels; "why not .."/"要不.."/dares ("you can't ..") are not.
_EN_NEGATION_RE = re.compile(
    r"(?<!\bnever\s)(?<!\bnot\s)(?<!\bwhy\s)(?<!n't\s)"
    r"(?:\b(?:never|not|avoid|without)|(?<!\bca)(?<!\bwo)(?<!\bcould)(?<!\bwould)n't)\s+(?:(?:ever|really|actually)\s+)?$",
    re.I,
)
_ZH_NEGATION_RE = re.compile(
    r"(?:(?:永远|绝对|千万)?(?:不要|不得|不能|不可|不许|禁止|严禁|切勿|勿|别)|(?<![要么何])(?:不会|不应(?:该)?|不))"
    r"(?:在[^，。；！？,.;!?\s]{1,8}?(?:里|中|时|内|上))?$"
)

_ATTACK_PERSONA_RE = re.compile(
    r"unrestricted|unfiltered|uncensored|jailbr[oe]ken|malicious|\bevil\b|(?<!ethical\s)hacker|(?-i:\bDAN\b)|\b(?:developer|god)\s+mode\b"
    r"|\b(?:no|without(?:\s+any)?)\s+(?:rules|restrictions?|limits|filters|ethics)\b"
    r"|无限制|不受限|没有(?:任何)?(?:限制|规则|道德)|(?<!白帽)黑客|恶意|越狱",
    re.I,
)

_CLAUSE_END_RE = re.compile(
    r"[ \t]*(?:$|[.,;:!?)\]。，；！？]"
    r"|(?:now|please|here|immediately|verbatim|exactly|completely|in\s+full|word\s+for\s+word)\b)",
    re.I | re.M,
)


def _is_negated(text: str, match: re.Match[str]) -> bool:
    """True when a negator directly precedes the match ("never print ...", "不要泄露...")."""
    lo = max(0, match.start() - _NEGATION_WINDOW)
    return bool(_EN_NEGATION_RE.search(text, lo, match.start()) or _ZH_NEGATION_RE.search(text, lo, match.start()))


def _is_attack_persona(text: str, match: re.Match[str]) -> bool:
    """True when an attack-persona marker follows a role assignment ("act as an unrestricted ...")."""
    return _ATTACK_PERSONA_RE.search(text, match.end(), match.end() + _PERSONA_WINDOW) is not None


def _is_explicit_extraction(text: str, match: re.Match[str]) -> bool:
    """Secret extraction aimed at the assistant itself ("your ...") or ending its clause."""
    return match.group("own") is not None or _CLAUSE_END_RE.match(text, match.end()) is not None


def _is_explicit_jailbreak(text: str, match: re.Match[str]) -> bool:
    """Mode/hypothetical frames are ordinary phrasing unless an attack persona accompanies them."""
    return match.group("soft") is None or _is_attack_persona(text, match)


# Categories whose hits count towards the block tier only when the gate passes.
_BLOCK_GATES: dict[str, _Gate] = {
    "role_confusion": _is_attack_persona,
    "role_confusion_zh": _is_attack_persona,
    "secret_extraction": _is_explicit_extraction,
    "jailbreak": _is_explicit_jailbreak,
    # Bare "forget everything" is ordinary; "... above/previous" targets the prompt.
    "forget_override": lambda _text, match: match.group("scope") is not None,
}

# Categories whose negated hits are protective phrasing and are dropped entirely.
_NEGATION_EXEMPT: frozenset[str] = frozenset({"secret_extraction", "secret_extraction_zh"})


# ---------------------------------------------------------------------------
# Result type + scan entry point
# ---------------------------------------------------------------------------

_BLOCK_THRESHOLD: float = 0.7


@dataclass
class GuardResult:
    """Result of input-side injection scanning.

    ``max_score``: strongest hit of any kind (durable stores gate on it — persisted
    content outlives the turn). ``unambiguous_score``: strongest hit conclusive on its
    own, behind ``block_score`` (live-input and rule-file gates); ``None`` = all count.
    """

    safe: bool
    patterns: list[str] = field(default_factory=list)
    max_score: float = 0.0
    unambiguous_score: float | None = None

    @property
    def block_score(self) -> float:
        """Strongest unambiguous signal (see ``_BLOCK_GATES``)."""
        return self.max_score if self.unambiguous_score is None else self.unambiguous_score

    @property
    def should_block(self) -> bool:
        """Whether the unambiguous signals are severe enough to warrant blocking."""
        return not self.safe and self.block_score >= _BLOCK_THRESHOLD


@dataclass
class _Tally:
    patterns: list[str] = field(default_factory=list)
    max_score: float = 0.0
    unambiguous_score: float = 0.0

    def record(self, name: str, score: float, *, unambiguous: bool) -> bool:
        """Record a hit; returns ``unambiguous`` so callers can stop at a conclusive one."""
        if name not in self.patterns:
            self.patterns.append(name)
        self.max_score = max(self.max_score, score)
        if unambiguous:
            self.unambiguous_score = max(self.unambiguous_score, score)
        return unambiguous


def _scan_text(text: str, tally: _Tally) -> None:
    """Run fast-path + category patterns against a single text variant."""
    for fast in _FAST_PATH_RE.finditer(text):
        if fast.lastgroup == "extract" and _is_negated(text, fast):
            continue
        unambiguous = fast.lastgroup != "role_zh" or _is_attack_persona(text, fast)
        if tally.record("fast_path_signature", _FAST_PATH_SCORE, unambiguous=unambiguous):
            break

    for name, score, pat in _CATEGORIES:
        gate = _BLOCK_GATES.get(name)
        for hit in pat.finditer(text):
            if name in _NEGATION_EXEMPT and _is_negated(text, hit):
                continue
            if tally.record(name, score, unambiguous=gate is None or gate(text, hit)):
                break


def scan_input(content: str) -> GuardResult:
    """Scan user input for prompt injection patterns.

    Two-pass detection: first on the raw text, then on an
    anti-obfuscation normalized variant (leet speak decoded,
    invisible Unicode stripped, whitespace collapsed).
    """
    if not content:
        return GuardResult(safe=True)

    tally = _Tally()

    # Pass 1: raw text
    _scan_text(content, tally)

    # Pass 2: normalized text (catches leet speak / invisible chars / spacing tricks)
    normalized = _normalize_for_detection(content)
    if normalized != content.lower():
        _scan_text(normalized, tally)

    if not tally.patterns:
        return GuardResult(safe=True)

    return GuardResult(
        safe=False,
        patterns=tally.patterns,
        max_score=tally.max_score,
        unambiguous_score=tally.unambiguous_score,
    )


def log_guard_result(result: GuardResult, content: str) -> None:
    """Log non-safe guard results at WARNING level."""
    if result.safe:
        return
    snippet = content[:200].replace("\n", " ")
    logger.warning(
        "[PROMPT_GUARD] patterns=%s score=%.2f snippet=%.200s", ",".join(result.patterns), result.max_score, snippet
    )
