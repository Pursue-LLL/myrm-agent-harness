"""Task specialty router — cross-vendor task domain specialty classification and routing.

Extracts task specialty features (CODE, LONG_DOC, REASONING, MULTIMODAL, CASUAL, GENERAL)
based on multi-dimensional signal scoring (lexical keywords, syntax blocks,
token/character length thresholds, math/LaTeX notation, media payloads, and session momentum).

[INPUT]
- query: str | list[dict[str, object]] (User query text or multimodal structure)
- specialty_model_slots: dict[TaskSpecialty, LLMConfig] (Optional mapping from specialty to model config)
- specialty_fallback_slots: dict[TaskSpecialty, LLMConfig] (Optional mapping from specialty to fallback config)
- default_model_cfg: LLMConfig (Base/Standard model configuration fallback)
- default_fallback_cfg: LLMConfig | None (Base fallback model configuration)
- recent_specialties: list[TaskSpecialty] | None (Session context for multi-turn momentum)

[OUTPUT]
- TaskSpecialty: Enum (CODE | LONG_DOC | REASONING | MULTIMODAL | CASUAL | GENERAL)
- SpecialtyRoutingResult: Dataclass (specialty, model_cfg, fallback_model_cfg, fallback_chain, confidence, reason)
- route_task_specialty(): Async function to route task to specialty model with multi-tier fallback chain

[POS]
Harness framework layer: toolkits/llms/routing/specialty_router.py.
Generic, zero-latency task specialty classifier running in pre-agent layer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from myrm_agent_harness.core.config.llm import LLMConfig

logger = logging.getLogger(__name__)

# Regular expressions for code syntax and structural features
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_\-\.\+]*\n[\s\S]*?```")
_CODE_KEYWORDS_RE = re.compile(
    r"\b(?:def|class|fn|func|function|import|from\s+\w+\s+import|const|let|var|package|struct|impl|async\s+def|async\s+fn|pub\s+fn|val|interface|enum)\b"
)
_MATH_NOTATION_RE = re.compile(
    r"\\(?:frac|sum|int|sqrt|lim|infty|partial|nabla|theta|alpha|beta|gamma|cdot|times|forall|exists)|"
    r"\$\$.+?\$\$|\\\[.+?\\\]",
    re.DOTALL,
)
_TRACEBACK_PATTERN_RE = re.compile(
    r"Traceback \(most recent call last\)|"
    r"(?:File\s+\".+?\",\s+line\s+\d+)|"
    r"(?:(?:TypeError|ValueError|KeyError|AttributeError|ImportError|RuntimeError"
    r"|IndexError|NameError|FileNotFoundError|PermissionError|OSError"
    r"|ConnectionError|TimeoutError|ModuleNotFoundError|ZeroDivisionError"
    r"|AssertionError|NotImplementedError|RecursionError|SyntaxError|IndentationError):\s+.+)"
)

# Long document threshold (characters ~ approximate tokens)
# ~24,000 characters is approximately 6k~10k tokens, triggering long-context specialization
LONG_DOC_CHAR_THRESHOLD = 24_000

# Short follow-up momentum threshold (characters)
_MOMENTUM_SHORT_THRESHOLD = 25


class TaskSpecialty(StrEnum):
    """Core domain specialties for cross-vendor model routing."""

    CODE = "code"
    LONG_DOC = "long_doc"
    REASONING = "reasoning"
    MULTIMODAL = "multimodal"
    CASUAL = "casual"
    GENERAL = "general"


DEFAULT_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "code",
        "coding",
        "代码",
        "写代码",
        "编程",
        "refactor",
        "重构",
        "implement",
        "实现",
        "function",
        "函数",
        "algorithm",
        "算法",
        "debug",
        "调试",
        "bug",
        "traceback",
        "报错",
        "fix",
        "修复",
        "compile",
        "编译",
        "unit test",
        "单元测试",
        "pytest",
        "vitest",
        "git",
        "repo",
        "repository",
        "仓库",
        "typescript",
        "python",
        "rust",
        "golang",
        "javascript",
        "java",
        "c++",
        "sql",
        "query",
        "orm",
        "api",
        "endpoint",
        "rest",
        "graphql",
        "docker",
        "kubernetes",
    }
)

DEFAULT_LONG_DOC_KEYWORDS: frozenset[str] = frozenset(
    {
        "full document",
        "entire document",
        "whole paper",
        "long paper",
        "全文",
        "长文档",
        "整篇文章",
        "整份报告",
        "300页",
        "白皮书",
        "whitepaper",
        "financial report",
        "财报",
        "annex",
        "附录",
        "needle in a haystack",
        "大海捞针",
        "exhaustive extract",
        "跨章节",
        "across all chapters",
    }
)

DEFAULT_REASONING_KEYWORDS: frozenset[str] = frozenset(
    {
        "prove",
        "proof",
        "证明",
        "derive",
        "derivation",
        "推导",
        "theorem",
        "定理",
        "lemma",
        "引理",
        "corollary",
        "推论",
        "mathematical induction",
        "数学归纳法",
        "formal verification",
        "形式化验证",
        "symbolic logic",
        "符号逻辑",
        "combinatorics",
        "组合数学",
        "game theory",
        "博弈论",
        "p versus np",
        "np-complete",
    }
)

DEFAULT_CASUAL_INDICATORS: frozenset[str] = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "你好",
        "您好",
        "在吗",
        "早上好",
        "晚上好",
        "早安",
        "晚安",
        "再见",
        "bye",
        "goodbye",
        "who are you",
        "你是谁",
    }
)


@dataclass(frozen=True)
class SpecialtyRoutingResult:
    """Result of task specialty classification and model selection."""

    specialty: TaskSpecialty
    model_cfg: LLMConfig
    fallback_model_cfg: LLMConfig | None = None
    fallback_chain: tuple[LLMConfig, ...] = ()
    confidence: float = 1.0
    reason: str = "default"


def _normalize_specialty_query(query: str | list[dict[str, object]]) -> tuple[str, bool]:
    """Normalize input query to plain text and detect multimodal presence."""
    if isinstance(query, str):
        return query, False

    texts: list[str] = []
    has_media = False
    for part in query:
        if not isinstance(part, dict):
            continue
        ptype = str(part.get("type", ""))
        if ptype == "text" and "text" in part:
            texts.append(str(part["text"]))
        elif ptype in ("image_url", "video_url", "image", "video", "audio", "file"):
            has_media = True

    return " ".join(texts), has_media


def _apply_specialty_momentum(
    raw_specialty: TaskSpecialty,
    clean_text: str,
    recent_specialties: list[TaskSpecialty] | None,
) -> tuple[TaskSpecialty, str | None]:
    """Apply session momentum to short follow-ups in continuous dialog."""
    if not recent_specialties or len(clean_text) >= _MOMENTUM_SHORT_THRESHOLD:
        return raw_specialty, None

    # Only inherit if raw classification was ambiguous or casual/general
    if raw_specialty in (TaskSpecialty.GENERAL, TaskSpecialty.CASUAL):
        # Look back up to 3 turns for strong technical specialty
        for prev in reversed(recent_specialties[-3:]):
            if prev in (TaskSpecialty.CODE, TaskSpecialty.REASONING, TaskSpecialty.LONG_DOC):
                return prev, f"momentum_inherited({prev.value})"

    return raw_specialty, None


def classify_task_specialty(
    query: str | list[dict[str, object]],
    *,
    recent_specialties: list[TaskSpecialty] | None = None,
    code_keywords: frozenset[str] | None = None,
    long_doc_keywords: frozenset[str] | None = None,
    reasoning_keywords: frozenset[str] | None = None,
    casual_indicators: frozenset[str] | None = None,
    long_doc_char_threshold: int = LONG_DOC_CHAR_THRESHOLD,
) -> tuple[TaskSpecialty, float, str]:
    """Classify the task into a primary domain specialty with confidence and reason.

    Evaluation hierarchy (Phase 1 zero-latency rule matching):
    1. Multimodal media presence -> MULTIMODAL
    2. Large character/token scale or explicit whole-doc keywords -> LONG_DOC
    3. Formal math notation / theorem proof keywords -> REASONING
    4. Code fences, traceback, programming keywords -> CODE
    5. Casual greetings / light chat indicators -> CASUAL
    6. Session Momentum -> Inherit previous technical specialty if short follow-up
    7. Fallback -> GENERAL

    Returns:
        tuple[TaskSpecialty, confidence, reason]
    """
    text, has_media = _normalize_specialty_query(query)
    clean_text = text.strip()

    if not clean_text and not has_media:
        return TaskSpecialty.GENERAL, 1.0, "empty_query"

    if has_media:
        return TaskSpecialty.MULTIMODAL, 1.0, "multimodal_media_present"

    # Check for Long Document characteristics
    text_len = len(clean_text)
    if text_len >= long_doc_char_threshold:
        return TaskSpecialty.LONG_DOC, 0.95, f"char_length_exceeded({text_len}>={long_doc_char_threshold})"

    ld_kw = long_doc_keywords or DEFAULT_LONG_DOC_KEYWORDS
    lower_text = clean_text.lower()
    for kw in ld_kw:
        if kw in lower_text:
            return TaskSpecialty.LONG_DOC, 0.85, f"long_doc_keyword_match({kw})"

    # Check for Mathematical Reasoning
    if _MATH_NOTATION_RE.search(clean_text):
        return TaskSpecialty.REASONING, 0.95, "math_latex_notation"

    rs_kw = reasoning_keywords or DEFAULT_REASONING_KEYWORDS
    for kw in rs_kw:
        if kw in lower_text:
            return TaskSpecialty.REASONING, 0.85, f"reasoning_keyword_match({kw})"

    # Check for Code Specialization
    if _CODE_FENCE_RE.search(clean_text):
        return TaskSpecialty.CODE, 0.95, "code_fence_block"

    if _TRACEBACK_PATTERN_RE.search(clean_text):
        return TaskSpecialty.CODE, 0.95, "traceback_error_log"

    if _CODE_KEYWORDS_RE.search(clean_text):
        return TaskSpecialty.CODE, 0.90, "code_syntax_declaration"

    cd_kw = code_keywords or DEFAULT_CODE_KEYWORDS
    code_match_count = 0
    for kw in cd_kw:
        if kw in lower_text:
            code_match_count += 1

    if code_match_count >= 2:
        return TaskSpecialty.CODE, 0.85, f"multiple_code_keywords({code_match_count})"
    elif code_match_count == 1:
        # Single code keyword with programming-oriented action verbs
        if any(v in lower_text for v in ("write", "create", "build", "refactor", "fix", "编写", "修改", "生成", "写一个")):
            return TaskSpecialty.CODE, 0.80, "code_action_intent"

    # Check for Casual Greetings / Light Chat
    cs_kw = casual_indicators or DEFAULT_CASUAL_INDICATORS
    if text_len < _MOMENTUM_SHORT_THRESHOLD and any(ind in lower_text for ind in cs_kw):
        return TaskSpecialty.CASUAL, 0.90, "casual_indicator_match"

    # Check Multi-turn Session Momentum
    momentum_specialty, momentum_reason = _apply_specialty_momentum(
        TaskSpecialty.GENERAL, clean_text, recent_specialties
    )
    if momentum_reason:
        return momentum_specialty, 0.80, momentum_reason

    return TaskSpecialty.GENERAL, 0.70, "general_default"


def _build_fallback_chain(
    primary: LLMConfig,
    specialty_fallback: LLMConfig | None,
    default_primary: LLMConfig,
    default_fallback: LLMConfig | None,
) -> tuple[LLMConfig, ...]:
    """Build a deduplicated four-tier fallback chain for robust recovery."""
    candidates: list[LLMConfig] = []
    seen: set[tuple[str, str | None]] = set()

    for item in (primary, specialty_fallback, default_primary, default_fallback):
        if item is None:
            continue
        key = (item.model, getattr(item, "api_base", None))
        if key not in seen:
            seen.add(key)
            candidates.append(item)

    return tuple(candidates)


async def route_task_specialty(
    query: str | list[dict[str, object]],
    default_model_cfg: LLMConfig,
    specialty_model_slots: dict[TaskSpecialty, LLMConfig] | None = None,
    specialty_fallback_slots: dict[TaskSpecialty, LLMConfig] | None = None,
    default_fallback_cfg: LLMConfig | None = None,
    recent_specialties: list[TaskSpecialty] | None = None,
    *,
    code_keywords: frozenset[str] | None = None,
    long_doc_keywords: frozenset[str] | None = None,
    reasoning_keywords: frozenset[str] | None = None,
    casual_indicators: frozenset[str] | None = None,
    long_doc_char_threshold: int = LONG_DOC_CHAR_THRESHOLD,
) -> SpecialtyRoutingResult:
    """Route a task to the appropriate specialized model slot or default with 4-tier fallback chain.

    Args:
        query: User input query
        default_model_cfg: Base model config used when no specialty slot is matched or configured
        specialty_model_slots: Optional map of specialty slots configured by user
        specialty_fallback_slots: Optional map of fallback configs per specialty
        default_fallback_cfg: Fallback for default model
        recent_specialties: Optional list of recent turn specialties for momentum
        code_keywords: Optional custom code keywords
        long_doc_keywords: Optional custom long doc keywords
        reasoning_keywords: Optional custom reasoning keywords
        casual_indicators: Optional custom casual indicators
        long_doc_char_threshold: Character threshold for long document specialty

    Returns:
        SpecialtyRoutingResult containing the chosen specialty, resolved LLMConfigs, and 4-tier fallback chain
    """
    specialty, confidence, reason = classify_task_specialty(
        query,
        recent_specialties=recent_specialties,
        code_keywords=code_keywords,
        long_doc_keywords=long_doc_keywords,
        reasoning_keywords=reasoning_keywords,
        casual_indicators=casual_indicators,
        long_doc_char_threshold=long_doc_char_threshold,
    )

    slots = specialty_model_slots or {}
    fallback_slots = specialty_fallback_slots or {}

    selected_cfg = slots.get(specialty)
    specialty_fallback_cfg = fallback_slots.get(specialty)

    if selected_cfg is not None:
        final_cfg = selected_cfg
        final_fallback = specialty_fallback_cfg or default_fallback_cfg
        final_reason = f"specialty_slot_hit({specialty.value}:{reason})"
    else:
        # Smooth degradation: fall back to default model config
        final_cfg = default_model_cfg
        final_fallback = default_fallback_cfg
        final_reason = f"specialty_slot_unconfigured_fallback({specialty.value}:{reason})"

    fallback_chain = _build_fallback_chain(
        primary=final_cfg,
        specialty_fallback=specialty_fallback_cfg,
        default_primary=default_model_cfg,
        default_fallback=default_fallback_cfg,
    )

    logger.info(
        "Specialty routing decision: specialty=%s model=%s reason=%s confidence=%.2f chain_length=%d",
        specialty.value,
        final_cfg.model,
        final_reason,
        confidence,
        len(fallback_chain),
    )

    return SpecialtyRoutingResult(
        specialty=specialty,
        model_cfg=final_cfg,
        fallback_model_cfg=final_fallback,
        fallback_chain=fallback_chain,
        confidence=confidence,
        reason=final_reason,
    )
