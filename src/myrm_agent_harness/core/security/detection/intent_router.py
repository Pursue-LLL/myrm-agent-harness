"""Input-side dangerous-intent safety router.

Detects high-risk destructive, exfiltrative, or privilege-mutation intents
in user input *before* starting the multi-step ReAct agent loop or invoking
expensive LLMs.

Categories:
1. MASS_DESTRUCTION: recursive file deletion, database drop/truncate all,
   disk format, repository history wipe.
2. MASS_EXFILTRATION: bulk dump/export of credentials, keys, or customer data
   to untrusted destinations.
3. PRIVILEGE_MUTATION: disabling security guardrails, sandbox escape,
   unauthorized root escalation.

Dual-Tier Zero-Latency Architecture:
- Tier 1: Pre-compiled regex pattern matching against normalized text (<0.2ms).
- Tier 2: Actionability vs. Informational/Code-Gen filter to ensure 0% false
  positives on developer code reviews, technical Q&A, and script generation.

[INPUT]
- content_boundary::strip_invisible_unicode (POS: Content boundary normalization.)

[OUTPUT]
- DangerousIntent: enum of high-risk intent categories.
- IntentSafetyResult: scan outcome dataclass.
- scan_dangerous_intent(text): entry point for intake intent safety routing.

[POS]
Intake-stage dangerous intent router for defense-in-depth before ReAct loops.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.core.security.detection.content_boundary import (
    strip_invisible_unicode,
)

logger = logging.getLogger(__name__)


class DangerousIntent(StrEnum):
    """Categories of high-risk actionable intents in user input."""

    MASS_DESTRUCTION = "mass-destruction"
    MASS_EXFILTRATION = "mass-exfiltration"
    PRIVILEGE_MUTATION = "privilege-mutation"


@dataclass(frozen=True, slots=True)
class IntentSafetyResult:
    """Outcome of intake dangerous intent scan."""

    safe: bool
    intent: DangerousIntent | None = None
    is_actionable: bool = False
    matched_pattern: str | None = None
    confidence: float = 0.0
    reason: str = ""


# ---------------------------------------------------------------------------
# Code block extraction & masking regexes
# ---------------------------------------------------------------------------
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Tier 2: Informational / Analytical / Code-Generation Indicators (Safe Context)
# ---------------------------------------------------------------------------
_INFORMATIONAL_RE = re.compile(
    r"(?i)\b(?:"
    r"why|how\s+to|what\s+is|explain|help\s+me\s+understand|debug|review|"
    r"analyze|analysis|difference\s+between|tutorial|guide|meaning\s+of|"
    r"is\s+it\s+safe|how\s+does|what\s+happens\s+if"
    r")\b|"
    r"(?:"
    r"为什么|如何|怎么|解释|分析|请问|区别|原理|教学|教程|报错原因|"
    r"帮我看看|代码审查|是什么意思|有什么影响|为什么会|怎么回事"
    r")"
)

_CODE_GEN_RE = re.compile(
    r"(?i)\b(?:"
    r"write|generate|create|implement|sample|mock|template|script\s+to|"
    r"code\s+(?:for|to)|function\s+to|snippet|example"
    r")\b|"
    r"(?:"
    r"写一个|编写|生成|实现|创建一个|写一段|样例|模板|代码示例|脚本示例|写个"
    r")"
)

# ---------------------------------------------------------------------------
# Tier 1: Dangerous Intent Patterns (EN + ZH)
# ---------------------------------------------------------------------------
_PATTERNS: tuple[tuple[DangerousIntent, str, re.Pattern[str]], ...] = (
    # --- 1. MASS_DESTRUCTION ---
    (
        DangerousIntent.MASS_DESTRUCTION,
        "destructive_shell_cmd",
        re.compile(
            r"(?i)(?:\b(?:rm\s+-(?:r[fv]|fr|rf)\s+(?:/|\*|~|\.\.|/var|/usr|/etc|/home|/root)|"
            r"rmdir\s+/[sq]\s+/[sq]|del\s+/[fs]\s+/[fs]\s+[a-z]:\\)\b)",
        ),
    ),
    (
        DangerousIntent.MASS_DESTRUCTION,
        "database_wipe_cmd",
        re.compile(
            r"(?i)\b(?:drop\s+(?:database|schema|all\s+tables)|"
            r"truncate\s+(?:all\s+)?tables?|"
            r"delete\s+from\s+[a-z0-9_`\"\.]+\s+where\s+(?:1\s*=\s*1|true))\b",
        ),
    ),
    (
        DangerousIntent.MASS_DESTRUCTION,
        "mass_disk_format_purge_en",
        re.compile(
            r"(?i)\b(?:wipe|nuke|format|purge|erase|shred|destroy|delete\s+all)\s+"
            r"(?:all|everything|the\s+(?:whole|entire)\s+(?:drive|disk|database|project|system|workspace|repo))\b",
        ),
    ),
    (
        DangerousIntent.MASS_DESTRUCTION,
        "mass_git_destructive_wipe",
        re.compile(
            r"(?i)\b(?:git\s+reset\s+--hard\s+HEAD~[0-9]{2,}|git\s+push\s+--force\s+origin\s+(?:main|master))\b",
        ),
    ),
    (
        DangerousIntent.MASS_DESTRUCTION,
        "mass_destruction_zh",
        re.compile(
            r"(?:清空|删除|抹掉|干掉|格掉|全扬了|重置).{0,6}(?:所有|全部|整个|全量).{0,6}"
            r"(?:数据库|数据表|库表|数据|硬盘|磁盘|根目录|系统文件|项目目录|代码库|工作区)"
            r"|(?:格式化|格盘|清盘|删库跑路|把整个项目扬了|把系统格了|把硬盘清空|把数据库全删了|把所有表都drop)"
        ),
    ),
    # --- 2. MASS_EXFILTRATION ---
    (
        DangerousIntent.MASS_EXFILTRATION,
        "bulk_credential_exfil_en",
        re.compile(
            r"(?i)\b(?:dump|export|extract|exfiltrate|send|leak|broadcast)\s+"
            r"(?:all|all\s+the|entire)\s+"
            r"(?:credentials?|passwords?|tokens?|api\s*keys?|secrets?|\.env\s*files?|private\s*keys?|customer\s+data)\s+"
            r"(?:to|externally|out|outside)\b",
        ),
    ),
    (
        DangerousIntent.MASS_EXFILTRATION,
        "bulk_credential_exfil_zh",
        re.compile(
            r"(?:导出|外发|打包|泄露|dump|发送).{0,6}(?:所有|全部|全量).{0,6}"
            r"(?:密码|密钥|tokens?|api\s*keys?|凭据|环境变量|\.env|私钥|用户数据|敏感数据).{0,6}"
            r"(?:到|给|外部|公网|第三方)",
        ),
    ),
    # --- 3. PRIVILEGE_MUTATION ---
    (
        DangerousIntent.MASS_DESTRUCTION,
        "guardrail_override_en",
        re.compile(
            r"(?i)\b(?:disable|bypass|deactivate|turn\s+off|kill|strip)\s+"
            r"(?:all\s+)?(?:security|guardrails?|sandbox|capability\s+fence|fencing|permissions?)\b",
        ),
    ),
    (
        DangerousIntent.PRIVILEGE_MUTATION,
        "privilege_escalation_zh",
        re.compile(
            r"(?:关闭|禁用|绕过|停用|解除|破坏).{0,6}(?:所有|全部)?\s*"
            r"(?:安全防御|安全护栏|沙箱隔离|权限围栏|安全拦截|安全限制|guardrails?)"
        ),
    ),
)


def _normalize_text(text: str) -> str:
    """Strip invisible Unicode and collapse extra whitespaces."""
    cleaned = strip_invisible_unicode(text)
    return _WHITESPACE_COLLAPSE_RE.sub(" ", cleaned).strip()


def scan_dangerous_intent(text: str) -> IntentSafetyResult:
    """Scan user input for actionable high-risk destructive intents.

    Evaluates text in two tiers:
    1. Tier 1: Fast pattern matching against normalized text.
    2. Tier 2: If a pattern matches, checks whether the text is actually
       an informational question (Q&A / code review) or code generation request.

    Returns:
        IntentSafetyResult: Detailed scan result indicating whether the
        input is safe to proceed to the agent ReAct loop.
    """
    if not text or not text.strip():
        return IntentSafetyResult(safe=True)

    norm_full = _normalize_text(text)

    # Strip code blocks to extract surrounding natural language intent
    text_without_code = _CODE_BLOCK_RE.sub(" ", norm_full)
    norm_nl = _WHITESPACE_COLLAPSE_RE.sub(" ", text_without_code).strip()

    # If the message is completely contained in a code block, use the full text
    eval_text = norm_nl if norm_nl else norm_full

    for intent, pattern_name, regex in _PATTERNS:
        match = regex.search(eval_text) or regex.search(norm_full)
        if match:
            matched_str = match.group(0)

            # Tier 2: Check for informational or code generation context
            is_informational = bool(_INFORMATIONAL_RE.search(eval_text))
            is_codegen = bool(_CODE_GEN_RE.search(eval_text))

            if is_informational or is_codegen:
                logger.info(
                    "[IntentRouter] Matched dangerous pattern '%s' but classified as safe (informational=%s, codegen=%s)",
                    pattern_name,
                    is_informational,
                    is_codegen,
                )
                return IntentSafetyResult(
                    safe=True,
                    intent=intent,
                    is_actionable=False,
                    matched_pattern=pattern_name,
                    confidence=0.5,
                    reason=f"informational_or_codegen: {pattern_name}",
                )

            logger.warning(
                "[IntentRouter] Dangerous actionable intent detected: intent=%s pattern=%s matched='%s'",
                intent.value,
                pattern_name,
                matched_str,
            )
            return IntentSafetyResult(
                safe=False,
                intent=intent,
                is_actionable=True,
                matched_pattern=pattern_name,
                confidence=1.0,
                reason=f"dangerous_intent_{intent.value}: {pattern_name}",
            )

    return IntentSafetyResult(safe=True)
