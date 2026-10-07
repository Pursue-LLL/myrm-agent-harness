"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/reranker.py
[INPUT]: Query text, candidate DecisionRecords, and timestamp context.
[OUTPUT]: Prioritized DecisionRecallHit list with Jaccard-0.8 dedup, MMR diversity, and chrono ranking.
"""

import re
from datetime import UTC, datetime

from .models import DecisionRecallHit, DecisionRecord, DecisionStatus

_DEDUP_JACCARD_THRESHOLD = 0.8
_MMR_LAMBDA = 0.7
_CHRONO_WEIGHT_PER_DAY = 0.15
_CHRONO_MAX_PENALTY = 1.0
_STRUCTURED_MIN_OVERLAP = 0.5

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+", re.UNICODE)
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]", re.UNICODE)

QUERY_STOPWORDS: frozenset[str] = frozenset({
    "的", "了", "是", "在", "和", "与", "及", "或", "把", "被", "就", "都", "而", "等",
    "之", "其", "这", "那", "也", "还", "于", "以", "为", "对", "从", "到", "吗", "呢",
    "吧", "啊", "哦", "嗯", "我", "你", "他", "她", "它", "我们", "你们", "他们", "咱们",
    "们", "怎么", "什么", "如何", "为啥", "为什么", "一个", "这个", "那个", "一下",
    "什", "么", "问", "请", "请问", "有", "没", "不", "无", "帮", "要", "想", "能",
    "会", "去", "来", "做", "写", "看", "查",
    "what", "is", "the", "are", "we", "our", "system", "please", "how", "why",
})


def tokenize(text: str) -> set[str]:
    """Tokenize multilingual text into normalized English words, CJK characters and bigrams."""
    tokens: set[str] = set()
    lowered = text.lower()

    # 1. English/Alphanumeric words
    for match in _WORD_PATTERN.finditer(lowered):
        w = match.group(0).strip()
        if w:
            tokens.add(w)

    # 2. CJK characters and 2-grams
    cjk_chars = _CJK_PATTERN.findall(lowered)
    for ch in cjk_chars:
        tokens.add(ch)
    for i in range(len(cjk_chars) - 1):
        tokens.add(cjk_chars[i] + cjk_chars[i + 1])

    return tokens


def tokenize_query(query: str) -> set[str]:
    """Tokenize search query with rigorous stopword and cross-boundary noise elimination."""
    tokens: set[str] = set()
    lowered = query.lower()

    # 1. Alphanumeric words
    for match in _WORD_PATTERN.finditer(lowered):
        w = match.group(0).strip()
        if w and w not in QUERY_STOPWORDS:
            tokens.add(w)

    # 2. CJK characters and clean 2-grams
    cjk_chars = _CJK_PATTERN.findall(lowered)
    for ch in cjk_chars:
        if ch not in QUERY_STOPWORDS:
            tokens.add(ch)
    for i in range(len(cjk_chars) - 1):
        c1, c2 = cjk_chars[i], cjk_chars[i + 1]
        if c1 not in QUERY_STOPWORDS and c2 not in QUERY_STOPWORDS:
            tokens.add(c1 + c2)

    return tokens if tokens else tokenize(query)


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard token similarity between two sets."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


def overlap_ratio(query_tokens: set[str], text_tokens: set[str]) -> float:
    """Compute intersection ratio of query tokens present in text."""
    if not query_tokens:
        return 0.0
    inter = len(query_tokens & text_tokens)
    return inter / len(query_tokens)


class StructuredPriorityReranker:
    """Reranker providing top-priority structured placement, MMR and ChronoRank."""

    @classmethod
    def score_and_rank(
        cls,
        query: str,
        records: list[DecisionRecord],
        now_utc: datetime | None = None,
        limit: int = 5,
    ) -> list[DecisionRecallHit]:
        """Filter records by query overlap, apply chronological penalization and format hits."""
        if not records or not query.strip():
            return []

        q_tokens = tokenize_query(query)
        if not q_tokens:
            return []

        now = now_utc or datetime.now(UTC)
        now_ts = now.timestamp()

        candidates: list[DecisionRecallHit] = []
        for r in records:
            r_tokens = tokenize(f"{r.title} {r.text} {r.rationale}")
            overlap = overlap_ratio(q_tokens, r_tokens)
            if overlap < _STRUCTURED_MIN_OVERLAP:
                continue

            # Calculate age penalty (max 1.0)
            try:
                rec_dt = datetime.fromisoformat(r.updated_at)
                age_days = max(0.0, (now_ts - rec_dt.timestamp()) / 86400.0)
            except (ValueError, TypeError):
                age_days = 0.0

            chrono_penalty = min(_CHRONO_MAX_PENALTY, _CHRONO_WEIGHT_PER_DAY * age_days)
            # Prioritized base score: negative to sort top in ascending or standard sort
            final_score = -(2.0 + overlap) + chrono_penalty

            status_label = "生效决策" if r.status == DecisionStatus.ACTIVE else (
                f"决策·已被取代→#{r.superseded_by or '?'}" if r.status == DecisionStatus.SUPERSEDED else "决策·已废弃"
            )
            line = f"【{status_label} #{r.id}】{r.title}：{r.text}"
            if r.rationale:
                line += f" （权衡理由：{r.rationale}）"
            if r.source_event:
                line += f" [{r.source_event}]"

            candidates.append(
                DecisionRecallHit(
                    decision_id=r.id,
                    title=r.title,
                    text=r.text,
                    rationale=r.rationale,
                    status=r.status,
                    supersedes_id=r.supersedes_id,
                    superseded_by=r.superseded_by,
                    score=final_score,
                    is_priority=True,
                    formatted_line=line,
                    source_event=r.source_event,
                    created_at=r.created_at,
                )
            )

        # 1. Dedup near duplicates (Jaccard >= 0.8)
        deduped = cls._dedup_near_duplicates(candidates)

        # 2. MMR diversity selection
        selected = cls._mmr_select(deduped, limit=limit)

        # 3. Sort by score ascending (most negative = highest priority)
        selected.sort(key=lambda h: h.score)
        return selected

    @classmethod
    def _dedup_near_duplicates(cls, hits: list[DecisionRecallHit]) -> list[DecisionRecallHit]:
        """Eliminate near-duplicate decision hits using Jaccard threshold 0.8."""
        kept: list[DecisionRecallHit] = []
        for hit in hits:
            hit_tokens = tokenize(f"{hit.title} {hit.text}")
            is_dup = False
            for idx, existing in enumerate(kept):
                existing_tokens = tokenize(f"{existing.title} {existing.text}")
                if jaccard_similarity(hit_tokens, existing_tokens) >= _DEDUP_JACCARD_THRESHOLD:
                    # Keep higher relevance (lower score)
                    if hit.score < existing.score:
                        kept[idx] = hit
                    is_dup = True
                    break
            if not is_dup:
                kept.append(hit)
        return kept

    @classmethod
    def _mmr_select(cls, hits: list[DecisionRecallHit], limit: int) -> list[DecisionRecallHit]:
        """Greedy Maximal Marginal Relevance selection for diverse top-K hits."""
        if len(hits) <= limit:
            return hits

        pool = list(hits)
        picked: list[DecisionRecallHit] = []
        picked_tokens: list[set[str]] = []

        while len(picked) < limit and pool:
            best_idx = 0
            best_mmr = float("-inf")
            for i, cand in enumerate(pool):
                cand_tokens = tokenize(f"{cand.title} {cand.text}")
                # Convert negative score to positive relevance: smaller score -> higher rel
                rel = 1.0 / (1.0 + max(0.0, cand.score + 2.0))
                max_sim = max((jaccard_similarity(pt, cand_tokens) for pt in picked_tokens), default=0.0)
                mmr_val = _MMR_LAMBDA * rel - (1.0 - _MMR_LAMBDA) * max_sim
                if mmr_val > best_mmr:
                    best_mmr = mmr_val
                    best_idx = i

            chosen = pool.pop(best_idx)
            picked.append(chosen)
            picked_tokens.append(tokenize(f"{chosen.title} {chosen.text}"))

        return picked

    @classmethod
    def format_prompt_block(cls, hits: list[DecisionRecallHit]) -> str:
        """Render markdown-formatted prioritized section with metacognitive boundary declaration."""
        if not hits:
            return ""

        lines = [
            "### 🏛️【生效架构决策与代际链】",
            "*(以下为经确认生效的技术选型决策，具备最高优先级，请勿发生方案漂移)*",
        ]
        for hit in hits:
            lines.append(f"- {hit.formatted_line}")

        lines.extend([
            "",
            "> ⚠️ **【元认知边界声明】** 未在上述列表中显式列出的技术选型 ≠ 不存在，请结合工程事实查验；支持通过 `#e<id>` 溯源原始对话上下文。",
        ])
        return "\n".join(lines)
