"""Task complexity router — unified scoring with session momentum and penalty feedback.

Phase 1 (rule-based, instant): weighted keyword/pattern matching with unified scoring.
Phase 2 (LLM judge, cached): uses filter LLM for ambiguous cases.
Momentum: prevents short follow-up messages from being downgraded to SIMPLE
when the conversation is operating at a higher tier.
Penalty: user-flagged misroutes penalize categories, improving accuracy over time.

[INPUT]
- agent.config.llm::LLMConfig (POS: LLM core. LiteLLM wrapper providing a unified multi-model invocation interface.)

[OUTPUT]
- route_task(): returns RoutingResult with selected tier and LLM config
- RoutingTier: SIMPLE | STANDARD | REASONING
- RoutingResult: dataclass with tier, model_cfg, fallback_model_cfg, reason
- _apply_momentum(): session momentum logic (exposed for testing)
- PenaltyTracker: per-category penalty tracking for misroute feedback

[POS]
Framework-level task complexity routing. Runs before Agent creation to
select the appropriate model tier based on query complexity and session context.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from myrm_agent_harness.core.config.llm import LLMConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_MATH_RE = re.compile(r"\\(?:frac|sum|int|sqrt|lim|infty|partial|nabla|theta|alpha|beta|gamma)")
_LATEX_BLOCK_RE = re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.DOTALL)

DEFAULT_STANDARD_KEYWORDS: frozenset[str] = frozenset(
    {
        "refactor",
        "重构",
        "implement",
        "implements",
        "optimize",
        "optimized",
        "debug",
        "调试",
        "migrate",
        "迁移",
        "deploy",
        "部署",
        "analyze",
        "分析",
        "review",
        "审查",
        "security",
        "performance",
        "性能",
        "database",
        "数据库",
        "infrastructure",
        "基础设施",
        "integration",
        "集成",
        "pipeline",
        "管道",
        "middleware",
        "中间件",
        "authentication",
        "authorization",
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
        "calculate",
        "Compute",
        "equation",
        "方程",
        "step by step",
        "逐步",
        "chain of thought",
        "思维链",
        "architect",
        "架构",
        "system design",
        "系统设计",
        "algorithm design",
        "算法设计",
        "complexity analysis",
        "复杂度分析",
        "formal verification",
        "形式化验证",
    }
)

DEFAULT_SIMPLE_INDICATORS: frozenset[str] = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "你好",
        "谢谢",
        "好",
        "嗯",
        "是",
        "对",
    }
)

DEFAULT_JUDGE_SYSTEM_PROMPT = (
    "You are a task complexity classifier. Classify the user's message into exactly one tier.\n"
    "SIMPLE = casual chat, short Q&A, greetings, simple factual questions\n"
    "STANDARD = coding, analysis, multi-step tasks, general technical questions\n"
    "REASONING = mathematical proofs, logical derivations, complex algorithms, system architecture design\n"
    "Rules:\n"
    "- When unsure, pick STANDARD\n"
    "- Short prompts with no technical depth → SIMPLE\n"
    "- Tasks requiring deep logical reasoning or formal proofs → REASONING\n"
    "- Queries requiring real-time data, external tools, web search, or file operations (e.g., weather, news, run code) MUST be STANDARD\n"
    'Output ONLY the raw JSON: {"tier":"SIMPLE"} or {"tier":"STANDARD"} or {"tier":"REASONING"}'
)


class RoutingTier(StrEnum):
    SIMPLE = "simple"
    STANDARD = "standard"
    REASONING = "reasoning"


@dataclass(frozen=True)
class RoutingResult:
    tier: RoutingTier
    model_cfg: LLMConfig
    fallback_model_cfg: LLMConfig | None
    reason: str


# ============ MR-14: Penalty Feedback System ============
# Per-category penalty tracking for misroute feedback.
# Mirrors manifest-router's SpecificityPenaltyService.


@dataclass
class PenaltyTracker:
    """Tracks user-flagged misroutes and applies per-tier penalties.

    When a user flags a routing decision as wrong, the tier gets penalized.
    Penalized tiers require stronger signals to activate, preventing repeated
    misroutes. Penalties decay over time (half-life configurable).

    Penalty formula: min(flag_count * PENALTY_PER_FLAG, PENALTY_CAP)
    """

    PENALTY_PER_FLAG: float = 0.75
    PENALTY_CAP: float = 3.0
    DECAY_HALF_LIFE_S: float = 86400.0  # 24 hours

    _flags: dict[str, list[float]] = field(default_factory=dict)

    def record_misroute(self, tier: RoutingTier) -> None:
        """Record a user-flagged misroute for the given tier."""
        key = tier.value
        if key not in self._flags:
            self._flags[key] = []
        self._flags[key].append(time.monotonic())
        logger.info("Penalty recorded for tier=%s (total=%d)", tier, len(self._flags[key]))

    def get_penalty(self, tier: RoutingTier) -> float:
        """Get current penalty for a tier, accounting for time decay."""
        key = tier.value
        timestamps = self._flags.get(key)
        if not timestamps:
            return 0.0

        now = time.monotonic()
        active_count = sum(
            1
            for ts in timestamps
            if (now - ts) < self.DECAY_HALF_LIFE_S * 3  # expire after 3 half-lives
        )

        if active_count == 0:
            self._flags.pop(key, None)
            return 0.0

        penalty = min(active_count * self.PENALTY_PER_FLAG, self.PENALTY_CAP)
        return penalty

    def apply_penalties(self, scores: dict[RoutingTier, float]) -> dict[RoutingTier, float]:
        """Apply penalties to tier scores, reducing penalized tiers."""
        adjusted = dict(scores)
        for tier in RoutingTier:
            penalty = self.get_penalty(tier)
            if penalty > 0:
                adjusted[tier] = max(0.0, adjusted.get(tier, 0.0) - penalty)
        return adjusted

    def cleanup_expired(self) -> int:
        """Remove expired flags. Returns number of entries removed."""
        now = time.monotonic()
        removed = 0
        for key in list(self._flags):
            before = len(self._flags[key])
            self._flags[key] = [ts for ts in self._flags[key] if (now - ts) < self.DECAY_HALF_LIFE_S * 3]
            removed += before - len(self._flags[key])
            if not self._flags[key]:
                del self._flags[key]
        return removed


# Global penalty tracker instance
_penalty_tracker = PenaltyTracker()


# ============ MR-15: Weighted Keywords ============
# Per-keyword weights for unified scoring.
# Mirrors manifest-router's KEYWORD_WEIGHTS + ACTIVATION_THRESHOLDS.


@dataclass(frozen=True)
class WeightedKeyword:
    """A keyword with an associated weight for scoring."""

    keyword: str
    weight: float = 1.0


def _build_weighted_keywords(
    keywords: frozenset[str],
    strong_weight: float = 2.0,
    weak_weight: float = 1.0,
) -> dict[str, float]:
    """Build weighted keyword dict from a frozenset.

    Strong anchors (multi-word, technical) get higher weight.
    Single common words get lower weight.
    """
    result: dict[str, float] = {}
    for kw in keywords:
        # Multi-word or technical keywords are stronger signals
        if " " in kw or len(kw) > 10:
            result[kw] = strong_weight
        else:
            result[kw] = weak_weight
    return result


# ============ MR-16: Unified Scoring Dimensions ============
# Structural and contextual signals for unified scoring.
# Mirrors manifest-router's structural-dimensions + contextual-dimensions.

_URL_RE = re.compile(r"https?://\S+")
_FILE_PATH_RE = re.compile(r"(?:/[\w.-]+){2,}|[\w.-]+\.(?:py|js|ts|java|go|rs|cpp|c|h)")
_EMAIL_RE = re.compile(r"[\w.-]+@[\w.-]+\.\w+")


def _score_structural_signals(text: str) -> dict[str, float]:
    """Score structural signals: URLs, file paths, emails.

    Returns dimension scores that feed into unified scoring.
    """
    scores: dict[str, float] = {}

    url_count = len(_URL_RE.findall(text))
    if url_count > 0:
        scores["urls"] = min(url_count * 0.5, 1.5)

    file_count = len(_FILE_PATH_RE.findall(text))
    if file_count > 0:
        scores["file_paths"] = min(file_count * 0.3, 1.0)

    return scores


def _score_contextual_signals(
    text: str,
    has_image: bool,
    word_count: int,
) -> dict[str, float]:
    """Score contextual signals: length, image, repetition requests.

    Returns dimension scores that feed into unified scoring.
    """
    scores: dict[str, float] = {}

    if has_image:
        scores["image_input"] = 6.0  # strong signal — vision models required

    if word_count > 50:
        scores["long_input"] = min((word_count - 50) * 0.02, 0.8)

    repetition_re = re.compile(
        r"(\d{1,6})\s*(?:variations?|options?|alternatives?|versions?|examples?|ways?\s+to)",
        re.IGNORECASE,
    )
    rep_match = repetition_re.search(text)
    if rep_match:
        n = int(rep_match.group(1))
        if n > 9:
            scores["repetition_request"] = 0.9
        elif n > 3:
            scores["repetition_request"] = 0.6
        elif n > 1:
            scores["repetition_request"] = 0.3

    return scores


def _normalize_query(query: str | list[dict[str, object]]) -> tuple[str, bool]:
    """Extract text from query and detect if it contains images."""
    if isinstance(query, str):
        return query, False

    text_parts: list[str] = []
    has_image = False
    for item in query:
        if isinstance(item, dict):
            if item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            elif item.get("type") in ("image_url", "image"):
                has_image = True
    return " ".join(text_parts), has_image


def _has_code_content(text: str) -> bool:
    return bool(_CODE_BLOCK_RE.search(text) or _INLINE_CODE_RE.search(text))


def _has_keywords(text: str, keywords: frozenset[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _has_math_content(text: str) -> bool:
    return bool(_MATH_RE.search(text) or _LATEX_BLOCK_RE.search(text))


def _is_simple_greeting(text: str, indicators: frozenset[str]) -> bool:
    stripped = text.strip().rstrip("!?！？。.").lower()
    return stripped in indicators


def _word_count(text: str) -> int:
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    latin_words = len(re.findall(r"[a-zA-Z]+", text))
    return cjk_chars + latin_words


def _compute_unified_score(
    text: str,
    has_image: bool,
    standard_keywords: frozenset[str],
    reasoning_keywords: frozenset[str],
    simple_indicators: frozenset[str],
) -> dict[RoutingTier, float]:
    """Compute unified scores for all tiers using multi-dimensional signals.

    Aggregates keyword, structural, and contextual signals into per-tier scores.
    Higher score = stronger signal for that tier.

    Returns dict mapping each RoutingTier to its aggregate score.
    """
    scores: dict[RoutingTier, float] = {
        RoutingTier.SIMPLE: 0.0,
        RoutingTier.STANDARD: 0.0,
        RoutingTier.REASONING: 0.0,
    }
    lower = text.lower()
    wc = _word_count(text)

    # --- Keyword signals (weighted) ---
    for kw in standard_keywords:
        if kw in lower:
            # Multi-word or technical keywords are stronger signals
            weight = 2.0 if (" " in kw or len(kw) > 10) else 1.0
            scores[RoutingTier.STANDARD] += weight

    for kw in reasoning_keywords:
        if kw in lower:
            weight = 2.0 if (" " in kw or len(kw) > 10) else 1.0
            scores[RoutingTier.REASONING] += weight

    # --- Simple greeting signal ---
    if _is_simple_greeting(text, simple_indicators):
        scores[RoutingTier.SIMPLE] += 5.0  # strong signal

    # --- Math signal ---
    if _has_math_content(text):
        scores[RoutingTier.REASONING] += 3.0

    # --- Code signal ---
    if _has_code_content(text):
        scores[RoutingTier.STANDARD] += 2.0

    # --- Structural signals (MR-16) ---
    structural = _score_structural_signals(text)
    if "urls" in structural:
        scores[RoutingTier.STANDARD] += structural["urls"]
    if "file_paths" in structural:
        scores[RoutingTier.STANDARD] += structural["file_paths"]

    # --- Contextual signals (MR-16) ---
    contextual = _score_contextual_signals(text, has_image, wc)
    if "image_input" in contextual:
        scores[RoutingTier.STANDARD] += contextual["image_input"]
    if "long_input" in contextual:
        scores[RoutingTier.STANDARD] += contextual["long_input"]
    if "repetition_request" in contextual:
        scores[RoutingTier.STANDARD] += contextual["repetition_request"]

    # --- Short message without signals → SIMPLE ---
    if wc <= 8 and scores[RoutingTier.STANDARD] < 1.0 and scores[RoutingTier.REASONING] < 1.0:
        scores[RoutingTier.SIMPLE] += 3.0

    # --- Long message without strong signals → STANDARD ---
    if wc > 50 and scores[RoutingTier.STANDARD] < 1.0 and scores[RoutingTier.REASONING] < 1.0:
        scores[RoutingTier.STANDARD] += 1.5

    return scores


# Scoring thresholds for tier activation
_TIER_THRESHOLDS: dict[RoutingTier, float] = {
    RoutingTier.SIMPLE: 2.0,
    RoutingTier.STANDARD: 1.5,
    RoutingTier.REASONING: 2.0,
}


def _rule_based_classify(
    text: str,
    has_image: bool,
    standard_keywords: frozenset[str],
    reasoning_keywords: frozenset[str],
    simple_indicators: frozenset[str],
) -> RoutingTier | None:
    """Phase 1: unified scoring classification. Returns None if ambiguous.

    Uses multi-dimensional scoring (keyword + structural + contextual) aggregated
    into per-tier scores, then selects the highest-scoring tier above its threshold.
    """
    scores = _compute_unified_score(text, has_image, standard_keywords, reasoning_keywords, simple_indicators)

    # Apply penalties (MR-14)
    scores = _penalty_tracker.apply_penalties(scores)

    # Find the best tier above its threshold
    best_tier: RoutingTier | None = None
    best_score = 0.0

    for tier, score in scores.items():
        threshold = _TIER_THRESHOLDS[tier]
        if score >= threshold and score > best_score:
            best_tier = tier
            best_score = score

    return best_tier


# ============ MR-17: Weighted Multi-Turn Momentum ============
# Weighted average momentum instead of median.
# Mirrors manifest-router's momentum.ts with tier-specific scores and length-based decay.

_TIER_SCORES: dict[RoutingTier, float] = {
    RoutingTier.SIMPLE: -0.2,
    RoutingTier.STANDARD: 0.0,
    RoutingTier.REASONING: 0.4,
}

_MOMENTUM_MAX_HISTORY = 5
_MOMENTUM_LONG_THRESHOLD = 100  # messages > 100 chars get zero momentum weight
_MOMENTUM_SHORT_THRESHOLD = 30  # messages < 30 chars get full momentum weight


def _apply_momentum(
    tier: RoutingTier,
    text: str,
    recent_tiers: list[RoutingTier] | None,
) -> tuple[RoutingTier, bool]:
    """Apply session momentum using weighted average (MR-17).

    Uses weighted average of recent tier scores instead of median.
    Momentum weight decays with message length:
    - <30 chars: full momentum (0.6)
    - 30-100 chars: linear decay
    - >100 chars: no momentum

    Also supports downgrading: if recent tiers are all SIMPLE but current
    tier is STANDARD/REASONING, apply negative momentum to prevent over-routing.

    Returns (adjusted_tier, was_overridden).
    """
    if not recent_tiers:
        return tier, False

    msg_len = len(text)

    # Compute momentum weight based on message length
    if msg_len > _MOMENTUM_LONG_THRESHOLD:
        momentum_weight = 0.0
    elif msg_len >= _MOMENTUM_SHORT_THRESHOLD:
        momentum_weight = 0.3 * (
            1.0 - (msg_len - _MOMENTUM_SHORT_THRESHOLD) / (_MOMENTUM_LONG_THRESHOLD - _MOMENTUM_SHORT_THRESHOLD)
        )
    else:
        momentum_weight = 0.3 + 0.3 * (1.0 - msg_len / _MOMENTUM_SHORT_THRESHOLD)

    if momentum_weight <= 0:
        return tier, False

    # Compute weighted average of recent tier scores
    recent_slice = recent_tiers[:_MOMENTUM_MAX_HISTORY]
    history_sum = sum(_TIER_SCORES.get(t, 0.0) for t in recent_slice)
    history_avg = history_sum / len(recent_slice)

    # Current tier score
    current_score = _TIER_SCORES.get(tier, 0.0)

    # Blended score
    effective_score = (1 - momentum_weight) * current_score + momentum_weight * history_avg

    # Map effective score back to tier
    # Thresholds are lower than raw scores because blended range is narrower.
    if effective_score >= 0.1:
        adjusted = RoutingTier.REASONING
    elif effective_score >= -0.1:
        adjusted = RoutingTier.STANDARD
    else:
        adjusted = RoutingTier.SIMPLE

    if adjusted != tier:
        logger.info(
            "Momentum override: %s → %s (weight=%.2f, history_avg=%.2f, effective=%.2f)",
            tier,
            adjusted,
            momentum_weight,
            history_avg,
            effective_score,
        )
        return adjusted, True

    return tier, False


_JUDGE_CACHE_MAX = 256
_JUDGE_CACHE_TTL_S = 300.0
_judge_cache: dict[str, tuple[str, float]] = {}

_TIER_PARSE_RE = re.compile(r'"tier"\s*:\s*"(SIMPLE|STANDARD|REASONING)"', re.IGNORECASE)

_JUDGE_TIER_MAP: dict[str, RoutingTier] = {
    "SIMPLE": RoutingTier.SIMPLE,
    "STANDARD": RoutingTier.STANDARD,
    "REASONING": RoutingTier.REASONING,
}


def _hash_text(text: str) -> str:
    return sha256(text.encode()).hexdigest()[:16]


def _cache_get(text_hash: str) -> RoutingTier | None:
    entry = _judge_cache.get(text_hash)
    if entry is None:
        return None
    tier_val, ts = entry
    if time.monotonic() - ts > _JUDGE_CACHE_TTL_S:
        _judge_cache.pop(text_hash, None)
        return None
    try:
        return RoutingTier(tier_val)
    except ValueError:
        _judge_cache.pop(text_hash, None)
        return None


def _cache_put(text_hash: str, tier: RoutingTier) -> None:
    if len(_judge_cache) >= _JUDGE_CACHE_MAX:
        oldest_key = next(iter(_judge_cache))
        _judge_cache.pop(oldest_key, None)
    _judge_cache[text_hash] = (tier.value, time.monotonic())


async def _llm_judge_classify(
    text: str,
    judge_llm: BaseChatModel,
    judge_system_prompt: str,
) -> RoutingTier:
    """Phase 2: LLM-based classification for ambiguous cases."""
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        response = await judge_llm.ainvoke(
            [
                SystemMessage(content=judge_system_prompt),
                HumanMessage(content=text[:500]),
            ]
        )
        content = str(response.content).strip()

        match = _TIER_PARSE_RE.search(content)
        if match:
            tier_str = match.group(1).upper()
            return _JUDGE_TIER_MAP.get(tier_str, RoutingTier.STANDARD)
    except Exception as e:
        logger.warning("LLM judge classification failed: %s", e)

    return RoutingTier.STANDARD


def _select_model_for_tier(
    tier: RoutingTier,
    standard_model_cfg: LLMConfig,
    light_model_cfg: LLMConfig | None,
    reasoning_model_cfg: LLMConfig | None,
    standard_fallback_cfg: LLMConfig | None,
    light_fallback_cfg: LLMConfig | None,
    reasoning_fallback_cfg: LLMConfig | None,
) -> tuple[LLMConfig, LLMConfig | None]:
    """Select model_cfg and fallback for a given tier with graceful degradation."""
    if tier == RoutingTier.SIMPLE:
        cfg = light_model_cfg or standard_model_cfg
        fallback = light_fallback_cfg or standard_fallback_cfg
        return cfg, fallback

    if tier == RoutingTier.REASONING:
        cfg = reasoning_model_cfg or standard_model_cfg
        fallback = reasoning_fallback_cfg or standard_fallback_cfg
        return cfg, fallback

    return standard_model_cfg, standard_fallback_cfg


# ============ MR-18: Content-Level Dedup ============
# Deduplicate identical queries to prevent repeated scoring.

_dedup_cache: dict[str, RoutingTier] = {}
_DEDUP_CACHE_MAX = 128


def _dedup_check(text: str) -> RoutingTier | None:
    """Check if this exact text was recently routed. Returns cached tier or None."""
    text_hash = _hash_text(text)
    return _dedup_cache.get(text_hash)


def _dedup_store(text: str, tier: RoutingTier) -> None:
    """Store routing result for content dedup."""
    if len(_dedup_cache) >= _DEDUP_CACHE_MAX:
        oldest_key = next(iter(_dedup_cache))
        _dedup_cache.pop(oldest_key, None)
    _dedup_cache[_hash_text(text)] = tier


async def route_task(
    query: str | list[dict[str, object]],
    standard_model_cfg: LLMConfig,
    light_model_cfg: LLMConfig | None = None,
    reasoning_model_cfg: LLMConfig | None = None,
    standard_fallback_cfg: LLMConfig | None = None,
    light_fallback_cfg: LLMConfig | None = None,
    reasoning_fallback_cfg: LLMConfig | None = None,
    judge_llm: BaseChatModel | None = None,
    *,
    recent_tiers: list[RoutingTier] | None = None,
    standard_keywords: frozenset[str] | None = None,
    reasoning_keywords: frozenset[str] | None = None,
    simple_indicators: frozenset[str] | None = None,
    judge_system_prompt: str | None = None,
    penalty_tracker: PenaltyTracker | None = None,
) -> RoutingResult:
    """Route a task to the appropriate model tier (3-tier).

    Uses unified multi-dimensional scoring (MR-16), weighted momentum (MR-17),
    penalty feedback (MR-14), and content dedup (MR-18).

    Args:
        query: User query (text or multimodal)
        standard_model_cfg: Primary model config — STANDARD tier
        light_model_cfg: Light model config — SIMPLE tier
        reasoning_model_cfg: Reasoning model config — REASONING tier
        standard_fallback_cfg: Fallback for STANDARD tier
        light_fallback_cfg: Fallback for SIMPLE tier
        reasoning_fallback_cfg: Fallback for REASONING tier
        judge_llm: Optional LLM for Phase 2 classification
        recent_tiers: Recent routing tiers from conversation history (for momentum)
        standard_keywords: Custom standard-tier keywords (defaults provided)
        reasoning_keywords: Custom reasoning-tier keywords (defaults provided)
        simple_indicators: Custom simple greeting indicators (defaults provided)
        judge_system_prompt: Custom LLM judge system prompt (default provided)
        penalty_tracker: Optional custom penalty tracker (uses global default)

    Returns:
        RoutingResult with selected tier, model config, fallback, and reason
    """
    std_kw = standard_keywords or DEFAULT_STANDARD_KEYWORDS
    reason_kw = reasoning_keywords or DEFAULT_REASONING_KEYWORDS
    simple_ind = simple_indicators or DEFAULT_SIMPLE_INDICATORS
    judge_prompt = judge_system_prompt or DEFAULT_JUDGE_SYSTEM_PROMPT

    select_args = (
        standard_model_cfg,
        light_model_cfg,
        reasoning_model_cfg,
        standard_fallback_cfg,
        light_fallback_cfg,
        reasoning_fallback_cfg,
    )

    text, has_image = _normalize_query(query)

    if not text.strip():
        cfg, fallback = _select_model_for_tier(RoutingTier.STANDARD, *select_args)
        return RoutingResult(
            tier=RoutingTier.STANDARD,
            model_cfg=cfg,
            fallback_model_cfg=fallback,
            reason="empty_query",
        )

    rule_result = _rule_based_classify(text, has_image, std_kw, reason_kw, simple_ind)
    if rule_result is not None:
        # MR-18: Content dedup — skip momentum for identical rule-based queries
        deduped = _dedup_check(text)
        if deduped is not None:
            cfg, fallback = _select_model_for_tier(deduped, *select_args)
            return RoutingResult(
                tier=deduped,
                model_cfg=cfg,
                fallback_model_cfg=fallback,
                reason="content_dedup",
            )

        final_tier, overridden = _apply_momentum(rule_result, text, recent_tiers)
        reason = "momentum_override" if overridden else "rule_based"
        cfg, fallback = _select_model_for_tier(final_tier, *select_args)
        logger.info(
            "Routing decision: tier=%s model=%s reason=%s",
            final_tier.value,
            cfg.model,
            reason,
        )
        _dedup_store(text, final_tier)
        return RoutingResult(tier=final_tier, model_cfg=cfg, fallback_model_cfg=fallback, reason=reason)

    if judge_llm is not None:
        text_hash = _hash_text(text)
        cached_tier = _cache_get(text_hash)
        if cached_tier is not None:
            cfg, fallback = _select_model_for_tier(cached_tier, *select_args)
            return RoutingResult(
                tier=cached_tier, model_cfg=cfg, fallback_model_cfg=fallback, reason="llm_judge_cached"
            )

        tier = await _llm_judge_classify(text, judge_llm, judge_prompt)
        _cache_put(text_hash, tier)

        cfg, fallback = _select_model_for_tier(tier, *select_args)
        logger.info(
            "Routing decision: tier=%s model=%s reason=llm_judge",
            tier.value,
            cfg.model,
        )
        return RoutingResult(tier=tier, model_cfg=cfg, fallback_model_cfg=fallback, reason="llm_judge")

    cfg, fallback = _select_model_for_tier(RoutingTier.STANDARD, *select_args)
    return RoutingResult(
        tier=RoutingTier.STANDARD,
        model_cfg=cfg,
        fallback_model_cfg=fallback,
        reason="default_standard",
    )


def record_misroute(tier: RoutingTier) -> None:
    """Record a user-flagged misroute for penalty feedback (MR-14).

    Call this when a user indicates the routing decision was wrong.
    The penalty will reduce the likelihood of that tier being selected
    for similar queries in the future.
    """
    _penalty_tracker.record_misroute(tier)


def get_penalty_tracker() -> PenaltyTracker:
    """Get the global penalty tracker instance."""
    return _penalty_tracker
