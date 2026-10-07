# [POS]: src/myrm_agent_harness/toolkits/memory/relational_backtrack/synonym_normalizer.py
# [INPUT]: None (pure normalization logic)
# [OUTPUT]: ActionSynonymNormalizer

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ActionSynonymNormalizer:
    """Action synonym normalization and dialect mapping engine.

    Resolves dialect and synonym variances (e.g., '打边炉' ↔ '吃火锅' ↔ 'hotpot')
    to bridge lexical mismatches that cause bare BM25 or raw string search to fail.
    """

    def __init__(self) -> None:
        self._canonical_to_synonyms: dict[str, set[str]] = {
            "eat_hotpot": {"吃火锅", "打边炉", "涮火锅", "涮羊肉", "hotpot"},
            "sign_contract": {"签约", "签合同", "签订合作协议", "签订合同", "签署协议", "sign_deal"},
            "deploy_service": {"发布", "上线", "部署", "发版", "deploy"},
            "code_review": {"代码评审", "代码审查", "代码复审", "cr", "code_review"},
            "online_meeting": {"开会", "线上会议", "语音沟通", "电话沟通", "sync_call"},
        }
        self._synonym_to_canonical: dict[str, str] = {}
        self._rebuild_reverse_index()

    def _rebuild_reverse_index(self) -> None:
        self._synonym_to_canonical.clear()
        for canonical, syns in self._canonical_to_synonyms.items():
            self._synonym_to_canonical[canonical.lower()] = canonical
            for s in syns:
                self._synonym_to_canonical[s.lower()] = canonical

    def register_synonyms(self, canonical: str, synonyms: list[str]) -> None:
        """Register a new canonical action and its synonym expressions."""
        clean_canonical = canonical.strip().lower()
        if clean_canonical not in self._canonical_to_synonyms:
            self._canonical_to_synonyms[clean_canonical] = set()

        for s in synonyms:
            clean_s = s.strip().lower()
            if clean_s:
                self._canonical_to_synonyms[clean_canonical].add(clean_s)

        self._rebuild_reverse_index()

    def canonicalize_action(self, action_text: str) -> str:
        """Resolve an action text to its canonical identifier."""
        clean_text = action_text.strip().lower()
        if clean_text in self._synonym_to_canonical:
            return self._synonym_to_canonical[clean_text]

        # Substring heuristic for compound expressions (e.g. "去吃火锅")
        for syn, canonical in self._synonym_to_canonical.items():
            if syn in clean_text or clean_text in syn:
                return canonical

        return clean_text

    def expand_synonyms(self, action_text: str) -> list[str]:
        """Return all synonym forms associated with the given action cue."""
        canonical = self.canonicalize_action(action_text)
        syns = self._canonical_to_synonyms.get(canonical, set())
        expanded = set(syns)
        expanded.add(canonical)
        return sorted(expanded)

    def compute_action_similarity(self, cue: str, candidate_action: str) -> float:
        """Compute matching score between a query cue and candidate action."""
        clean_cue = cue.strip().lower()
        clean_cand = candidate_action.strip().lower()

        if clean_cue == clean_cand:
            return 1.0

        canon_cue = self.canonicalize_action(clean_cue)
        canon_cand = self.canonicalize_action(clean_cand)

        if canon_cue == canon_cand:
            return 0.95

        if clean_cue in clean_cand or clean_cand in clean_cue:
            return 0.8

        return 0.0
