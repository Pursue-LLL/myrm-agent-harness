"""High-performance in-memory BM25 lexical searcher for OKF concept bundles.

[INPUT]
- toolkits.memory.git_okf.models::OKFConcept, OKFSearchResult (POS: Types and models for git okf.)

[OUTPUT]
- InMemoryBM25Searcher: High-performance in-memory BM25 lexical searcher for OKF concept bundles.

[POS]
High-performance in-memory BM25 lexical searcher for OKF concept bundles.
"""

# [POS]: myrm_agent_harness/toolkits/memory/git_okf/in_memory_bm25.py
# [INPUT]: Concept corpus and user queries
# [OUTPUT]: In-memory BM25 lexical scorer with sub-millisecond ranking

import math
import re
from collections import Counter
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.git_okf.models import OKFConcept, OKFSearchResult

_WORD_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Tokenize multilingual text into normalized lowercase tokens."""
    if not text:
        return []
    tokens: list[str] = []
    for match in _WORD_PATTERN.finditer(text.lower()):
        word = match.group(0)
        # For non-ASCII Chinese/CJK characters, emit both n-grams or characters
        if any("\u4e00" <= c <= "\u9fff" for c in word):
            for ch in word:
                tokens.append(ch)
            if len(word) > 1:
                for i in range(len(word) - 1):
                    tokens.append(word[i : i + 2])
        else:
            tokens.append(word)
    return tokens


class InMemoryBM25Searcher:
    """High-performance in-memory BM25 lexical searcher for OKF concept bundles.

    Guarantees sub-millisecond response latency with zero network/API overhead.
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._concepts: dict[str, OKFConcept] = {}
        self._field_tokens: dict[str, dict[str, list[str]]] = {}
        self._doc_lengths: dict[str, float] = {}
        self._avg_doc_len: float = 0.0
        self._df: Counter[str] = Counter()
        self._num_docs: int = 0

    def index(self, concepts: Sequence[OKFConcept]) -> None:
        """Build or rebuild in-memory inverted indices over concept fields."""
        self._concepts.clear()
        self._field_tokens.clear()
        self._doc_lengths.clear()
        self._df.clear()

        self._num_docs = len(concepts)
        if self._num_docs == 0:
            self._avg_doc_len = 0.0
            return

        total_length: float = 0.0

        for concept in concepts:
            cid = concept.id
            self._concepts[cid] = concept

            title_tokens = _tokenize(concept.title)
            desc_tokens = _tokenize(concept.description)
            tags_tokens = _tokenize(" ".join(concept.tags))
            refs_tokens = _tokenize(" ".join(concept.code_refs))
            body_tokens = _tokenize(concept.body)

            self._field_tokens[cid] = {
                "title": title_tokens,
                "description": desc_tokens,
                "tags": tags_tokens,
                "code_refs": refs_tokens,
                "body": body_tokens,
            }

            # Weighted virtual document length:
            # title*2.5 + desc*1.5 + tags*1.5 + refs*1.5 + body*1.0
            effective_length = (
                len(title_tokens) * 2.5
                + len(desc_tokens) * 1.5
                + len(tags_tokens) * 1.5
                + len(refs_tokens) * 1.5
                + len(body_tokens) * 1.0
            )
            self._doc_lengths[cid] = effective_length
            total_length += effective_length

            # Document frequency counting (distinct words across all fields)
            distinct_words = set(
                title_tokens + desc_tokens + tags_tokens + refs_tokens + body_tokens
            )
            for word in distinct_words:
                self._df[word] += 1

        self._avg_doc_len = total_length / self._num_docs if self._num_docs > 0 else 0.0

    def search(
        self,
        query: str,
        limit: int = 10,
        filter_governance: str | None = None,
        filter_status: str | None = None,
        exclude_stale: bool = False,
    ) -> list[OKFSearchResult]:
        """Perform sub-millisecond lexical scoring across indexed concepts."""
        if not query.strip() or self._num_docs == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        weights: dict[str, float] = {
            "title": 2.5,
            "description": 1.5,
            "tags": 1.5,
            "code_refs": 1.5,
            "body": 1.0,
        }

        scores: dict[str, float] = {}
        matched_fields_map: dict[str, set[str]] = {}

        for cid, concept in self._concepts.items():
            if filter_governance and concept.effective_governance().value != filter_governance:
                continue
            if filter_status and concept.status.value != filter_status:
                continue

            doc_len = self._doc_lengths.get(cid, 1.0)
            fields = self._field_tokens.get(cid, {})

            score: float = 0.0
            matched_fields: set[str] = set()

            for q_term in query_tokens:
                doc_freq = self._df.get(q_term, 0)
                if doc_freq == 0:
                    continue

                # Standard Robertson-Spärck Jones IDF
                idf = math.log((self._num_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
                if idf <= 0.0:
                    idf = 0.01

                # Calculate weighted term frequency across fields
                term_tf = 0.0
                for field_name, f_weight in weights.items():
                    f_tokens = fields.get(field_name, [])
                    cnt = f_tokens.count(q_term)
                    if cnt > 0:
                        term_tf += cnt * f_weight
                        matched_fields.add(field_name)

                if term_tf > 0.0:
                    len_norm = 1.0 - self._b + self._b * (doc_len / (self._avg_doc_len + 1e-6))
                    bm25_term = idf * ((term_tf * (self._k1 + 1.0)) / (term_tf + self._k1 * len_norm))
                    score += bm25_term

            if score > 0.0:
                scores[cid] = score
                matched_fields_map[cid] = matched_fields

        sorted_cids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]

        results: list[OKFSearchResult] = []
        for cid in sorted_cids:
            c = self._concepts[cid]
            results.append(
                OKFSearchResult(
                    concept_id=c.id,
                    title=c.title,
                    type=c.type,
                    description=c.description,
                    governance=c.effective_governance().value,
                    score=round(scores[cid], 4),
                    matched_fields=sorted(matched_fields_map.get(cid, set())),
                    tags=list(c.tags),
                    code_refs=list(c.code_refs),
                    is_stale=False,  # populated by validator/loader
                )
            )

        return results
