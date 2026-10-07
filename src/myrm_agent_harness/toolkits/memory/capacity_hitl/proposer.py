"""[POS]: src/myrm_agent_harness/toolkits/memory/capacity_hitl/proposer.py
[INPUT]: Candidate memory entry models and similarity threshold parameters.
[OUTPUT]: Read-only HitlCandidateProposal lists for human review.
"""

import hashlib
import time
import uuid

from myrm_agent_harness.toolkits.memory.capacity_hitl.models import (
    CandidateActionKind,
    HitlCandidateProposal,
    HitlCandidateStatus,
    MemoryEntryRef,
)


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    # 词级 Jaccard (适用于英文及有空格的语言)
    words_a = {w for w in text_a.lower().split() if w}
    words_b = {w for w in text_b.lower().split() if w}
    word_sim = (
        len(words_a & words_b) / len(words_a | words_b)
        if (words_a and words_b)
        else 0.0
    )

    # 字符级 Jaccard (适用于中文及多语言短语)
    chars_a = {c for c in text_a if not c.isspace()}
    chars_b = {c for c in text_b if not c.isspace()}
    char_sim = (
        len(chars_a & chars_b) / len(chars_a | chars_b)
        if (chars_a and chars_b)
        else 0.0
    )

    return max(word_sim, char_sim)


class MergeArchiveCandidateProposer:
    """Read-only candidate proposer formulating merge and archive recommendations without mutating data."""

    def __init__(self, similarity_threshold: float = 0.40) -> None:
        self._similarity_threshold = similarity_threshold

    def propose_candidates(
        self,
        entries: list[dict[str, str | int | float | list[str]]],
        max_proposals: int = 10,
    ) -> list[HitlCandidateProposal]:
        """Examine entries to discover mergeable overlaps and archive-ready stale items."""
        structured_entries: list[MemoryEntryRef] = []
        for e in entries:
            content_str = str(e.get("content", ""))
            tags_list = [str(t) for t in e.get("tags", [])] if isinstance(e.get("tags"), list) else []
            structured_entries.append(
                MemoryEntryRef(
                    id=str(e.get("id", "")),
                    content=content_str,
                    content_hash=_compute_hash(content_str),
                    tags=tags_list,
                    created_at=float(e.get("created_at", time.time())),
                    access_count=int(e.get("access_count", 0)),
                )
            )

        proposals: list[HitlCandidateProposal] = []
        merged_pair_ids: set[str] = set()

        # 1. 挖掘合并候选对 (Merge Candidates)
        n = len(structured_entries)
        for i in range(n):
            if len(proposals) >= max_proposals:
                break
            entry_a = structured_entries[i]
            if entry_a.id in merged_pair_ids:
                continue

            for j in range(i + 1, n):
                entry_b = structured_entries[j]
                if entry_b.id in merged_pair_ids:
                    continue

                sim = _jaccard_similarity(entry_a.content, entry_b.content)
                if sim >= self._similarity_threshold:
                    merged_pair_ids.add(entry_a.id)
                    merged_pair_ids.add(entry_b.id)

                    proposed_text = f"{entry_a.content}；补充：{entry_b.content}"
                    proposals.append(
                        HitlCandidateProposal(
                            candidate_id=f"hitl-merge-{uuid.uuid4().hex[:8]}",
                            action_kind=CandidateActionKind.MERGE,
                            source_entries=[entry_a, entry_b],
                            proposed_content=proposed_text,
                            reason=f"检测到条目内容高度重叠 (词素相似度 {sim:.2f})，建议合并为单条以精简配额。",
                            confidence=round(min(0.98, sim + 0.1), 2),
                            status=HitlCandidateStatus.PENDING,
                            created_at=time.time(),
                        )
                    )
                    break

        # 2. 挖掘归档候选 (Archive Candidates: 访问次数为 0 或极低，且未参与合并)
        for entry in structured_entries:
            if len(proposals) >= max_proposals:
                break
            if entry.id in merged_pair_ids:
                continue

            if entry.access_count == 0:
                proposals.append(
                    HitlCandidateProposal(
                        candidate_id=f"hitl-archive-{uuid.uuid4().hex[:8]}",
                        action_kind=CandidateActionKind.ARCHIVE,
                        source_entries=[entry],
                        proposed_content="[待归档至冷存储]",
                        reason="条目长期为零调用冷门数据，建议转入低频归档区以释放活跃配额，绝不永久物理删除。",
                        confidence=0.88,
                        status=HitlCandidateStatus.PENDING,
                        created_at=time.time(),
                    )
                )

        return proposals
