"""Grounded Dreaming Engine with Provenance Anchoring and Redline Governance.

[POS]
做梦认知聚类蒸馏引擎。在空闲周期执行跨会话事实聚类、共识加权、敏感信息红线拦截、
多项目作用域隔离，并将结构化双向溯源锚点绑定至梦境日记条目。

[INPUT]
- fragments: 跨会话对话记忆碎片列表
- target_project_id: 可选的目标项目范围约束

[OUTPUT]
- GroundedDreamingEngine: 具备溯源锚定与隔离防护的做梦认知聚类引擎
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamDiaryEntry,
    DreamSessionFragment,
)
from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    MemoryProvenanceAnchor,
    ProjectScopeIsolationGuard,
    SensitiveProvenanceGuard,
)

_TOKEN_REGEX = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class GroundedDreamingEngine:
    """Consolidates cross-session conversational memory fragments with provenance tracking."""

    def __init__(self, similarity_threshold: float = 0.35) -> None:
        self._similarity_threshold = similarity_threshold

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        """Extract alphanumeric and CJK word tokens."""
        return {tok.lower() for tok in _TOKEN_REGEX.findall(text) if len(tok) > 1}

    @classmethod
    def _jaccard_similarity(cls, tokens_a: set[str], tokens_b: set[str]) -> float:
        """Calculate Jaccard index between two token sets."""
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        return float(intersection / union) if union > 0 else 0.0

    def process_fragments(
        self,
        fragments: Sequence[DreamSessionFragment],
        target_project_id: str | None = None,
    ) -> list[DreamDiaryEntry]:
        """Process session fragments into consolidated dream diary entries with provenance anchors."""
        if not fragments:
            return []

        # 1. Flatten memory facts into unified candidates with origin tracking & safety screening
        candidates: list[dict[str, object]] = []
        for frag in fragments:
            # Check scope isolation
            frag_proj = frag.project_id
            if not ProjectScopeIsolationGuard.validate_scope(frag_proj, target_project_id):
                continue

            for mem in frag.memories:
                content = str(mem.get("content", "")).strip()
                if not content:
                    continue

                # Sensitive credential redline filter (100% block)
                if SensitiveProvenanceGuard.contains_sensitive_content(content):
                    continue

                evidences = mem.get("evidence")
                evidence_snippets: list[str] = []
                anchors: list[MemoryProvenanceAnchor] = []

                if isinstance(evidences, list):
                    for ev in evidences:
                        if isinstance(ev, dict):
                            quote = str(ev.get("quote_snippet") or ev.get("verbatim_quote") or "")
                            if quote and not SensitiveProvenanceGuard.contains_sensitive_content(quote):
                                evidence_snippets.append(quote)
                                msg_id = str(ev.get("message_id") or f"msg_{frag.session_id}")
                                speaker = str(ev.get("speaker") or "user")
                                anchors.append(
                                    MemoryProvenanceAnchor(
                                        session_id=frag.session_id,
                                        message_id=msg_id,
                                        speaker=speaker,
                                        timestamp=frag.extracted_at,
                                        verbatim_quote=quote,
                                        project_id=frag_proj,
                                    )
                                )
                        elif isinstance(ev, str) and ev:
                            if not SensitiveProvenanceGuard.contains_sensitive_content(ev):
                                evidence_snippets.append(ev)

                # Fallback: create primary provenance anchor if evidence snippets are plain
                if not anchors and evidence_snippets:
                    anchors.append(
                        MemoryProvenanceAnchor(
                            session_id=frag.session_id,
                            message_id=f"msg_{frag.session_id}",
                            speaker="user",
                            timestamp=frag.extracted_at,
                            verbatim_quote=evidence_snippets[0],
                            project_id=frag_proj,
                        )
                    )

                candidates.append(
                    {
                        "session_id": frag.session_id,
                        "project_id": frag_proj,
                        "content": content,
                        "tokens": self._tokenize(content),
                        "evidence_snippets": evidence_snippets,
                        "provenance_anchors": anchors,
                        "confidence": float(mem.get("confidence", 0.5)),  # type: ignore[arg-type]
                    }
                )

        if not candidates:
            return []

        # 2. Cluster candidate facts across sessions
        clusters: list[list[dict[str, object]]] = []
        for cand in candidates:
            cand_tokens = cand["tokens"]
            assert isinstance(cand_tokens, set)
            matched_cluster: list[dict[str, object]] | None = None
            for cluster in clusters:
                for member in cluster:
                    member_tokens = member["tokens"]
                    assert isinstance(member_tokens, set)
                    sim = self._jaccard_similarity(cand_tokens, member_tokens)
                    if sim >= self._similarity_threshold:
                        matched_cluster = cluster
                        break
                if matched_cluster is not None:
                    break

            if matched_cluster is not None:
                matched_cluster.append(cand)
            else:
                clusters.append([cand])

        # 3. Distill clusters into DreamDiaryEntries
        entries: list[DreamDiaryEntry] = []
        for cluster in clusters:
            session_ids = sorted({str(m["session_id"]) for m in cluster})
            all_snippets: list[str] = []
            all_anchors: list[MemoryProvenanceAnchor] = []

            for m in cluster:
                snippets = m.get("evidence_snippets")
                if isinstance(snippets, list):
                    for s in snippets:
                        if isinstance(s, str) and s and s not in all_snippets:
                            all_snippets.append(s)

                anchors = m.get("provenance_anchors")
                if isinstance(anchors, list):
                    for a in anchors:
                        if isinstance(a, MemoryProvenanceAnchor) and a not in all_anchors:
                            all_anchors.append(a)

            best_cand = max(
                cluster,
                key=lambda x: (
                    float(x.get("confidence", 0.5)),  # type: ignore[arg-type]
                    len(str(x.get("content", ""))),
                ),
            )
            base_statement = str(best_cand["content"])

            session_count = len(session_ids)
            if session_count >= 2:
                statement = f"[Cross-Session Validated] {base_statement}"
                conf_delta = min(0.35, 0.1 * session_count)
            else:
                statement = base_statement
                conf_delta = 0.1

            entries.append(
                DreamDiaryEntry.create(
                    cognitive_statement=statement,
                    source_session_ids=session_ids,
                    evidence_snippets=all_snippets[:5],
                    confidence_delta=round(conf_delta, 2),
                    provenance_anchors=all_anchors,
                    project_id=target_project_id or str(best_cand.get("project_id") or ""),
                )
            )

        entries.sort(
            key=lambda e: (len(e.source_session_ids), e.confidence_delta),
            reverse=True,
        )
        return entries
