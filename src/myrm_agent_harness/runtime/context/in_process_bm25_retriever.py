"""In-process sub-millisecond BM25 lexical retriever for AI agent context engineering.

Zero-dependency, zero GPU, purely in-memory inverted index and Okapi BM25 scoring.
Target latency < 0.5ms for tool schema and context segment retrieval.
Strict 0 Any, type-hinted, thread-safe.

[INPUT]
- runtime.context.in_process_bm25_types::BM25Document, BM25SearchResult (POS: Type definitions for
  In-Process BM25 Lexical Retriever and Dynamic Tool Schema Pruner.)

[OUTPUT]
- tokenize_lexical: Fast lexical tokenizer splitting code identifiers, snake_case, and natural language.
- InProcessBM25Retriever: Sub-millisecond in-process Okapi BM25 engine with inverted indexing.

[POS]
In-process sub-millisecond BM25 lexical retriever for AI agent context engineering.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from .in_process_bm25_types import BM25Document, BM25SearchResult

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fa5]+")


def tokenize_lexical(text: str) -> tuple[str, ...]:
    """Fast lexical tokenizer splitting code identifiers, snake_case, and natural language.

    Splits snake_case and camelCase tokens into base words, converts to lowercase.
    """
    if not text:
        return ()

    raw_tokens = _WORD_PATTERN.findall(text)
    tokens: list[str] = []
    for raw in raw_tokens:
        # Split camelCase and snake_case
        sub_tokens = re.sub(r"([a-z])([A-Z])", r"\1_\2", raw).split("_")
        for st in sub_tokens:
            cleaned = st.strip().lower()
            if len(cleaned) >= 2 or re.match(r"[\u4e00-\u9fa5]", cleaned):
                tokens.append(cleaned)
    return tuple(tokens)


class InProcessBM25Retriever:
    """Sub-millisecond in-process Okapi BM25 engine with inverted indexing."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._lock = threading.RLock()
        self._documents: dict[str, BM25Document] = {}
        self._doc_lengths: dict[str, int] = {}
        self._doc_frequencies: dict[str, int] = defaultdict(int)
        self._inverted_index: dict[str, dict[str, int]] = defaultdict(dict)
        self._avg_doc_length: float = 0.0

    def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: Mapping[str, str | int | float | bool] | None = None,
    ) -> BM25Document:
        """Index a single document into the in-memory inverted index."""
        with self._lock:
            tokens = tokenize_lexical(content)
            doc = BM25Document(
                doc_id=doc_id,
                content=content,
                tokens=tokens,
                metadata=metadata or {},
            )
            self._documents[doc_id] = doc
            self._rebuild_index_locked()
            return doc

    def index_documents_batch(
        self,
        docs: Sequence[tuple[str, str, Mapping[str, str | int | float | bool]]],
    ) -> int:
        """Batch index multiple documents atomically."""
        with self._lock:
            for doc_id, content, meta in docs:
                tokens = tokenize_lexical(content)
                self._documents[doc_id] = BM25Document(
                    doc_id=doc_id,
                    content=content,
                    tokens=tokens,
                    metadata=meta,
                )
            self._rebuild_index_locked()
            return len(docs)

    def remove_document(self, doc_id: str) -> bool:
        """Remove a document from the index."""
        with self._lock:
            if doc_id in self._documents:
                del self._documents[doc_id]
                self._rebuild_index_locked()
                return True
            return False

    def clear(self) -> None:
        """Clear all indexed documents."""
        with self._lock:
            self._documents.clear()
            self._doc_lengths.clear()
            self._doc_frequencies.clear()
            self._inverted_index.clear()
            self._avg_doc_length = 0.0

    def _rebuild_index_locked(self) -> None:
        """Recompute inverted index, document frequencies, and average length."""
        self._doc_lengths.clear()
        self._doc_frequencies.clear()
        self._inverted_index.clear()

        n_docs = len(self._documents)
        if n_docs == 0:
            self._avg_doc_length = 0.0
            return

        total_length = 0
        for doc_id, doc in self._documents.items():
            doc_len = len(doc.tokens)
            self._doc_lengths[doc_id] = doc_len
            total_length += doc_len

            term_counts = Counter(doc.tokens)
            for term, count in term_counts.items():
                self._inverted_index[term][doc_id] = count
                self._doc_frequencies[term] += 1

        self._avg_doc_length = total_length / n_docs

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[BM25SearchResult, ...]:
        """Query the index and return ranked results with BM25 scores."""
        query_tokens = tokenize_lexical(query)
        if not query_tokens:
            return ()

        with self._lock:
            n_docs = len(self._documents)
            if n_docs == 0:
                return ()

            scores: dict[str, float] = defaultdict(float)
            avgdl = self._avg_doc_length or 1.0

            for q_term in set(query_tokens):
                df = self._doc_frequencies.get(q_term, 0)
                if df == 0:
                    continue

                # Robertson-Spärck Jones IDF with smoothing
                idf = math.log(((n_docs - df + 0.5) / (df + 0.5)) + 1.0)
                postings = self._inverted_index.get(q_term, {})

                for doc_id, tf in postings.items():
                    doc_len = self._doc_lengths.get(doc_id, 1)
                    denom = tf + self._k1 * (1.0 - self._b + self._b * (doc_len / avgdl))
                    term_score = idf * (tf * (self._k1 + 1.0) / (denom if denom > 0 else 1.0))
                    scores[doc_id] += term_score

            # Rank and format results
            ranked_items = sorted(
                [
                    (doc_id, score)
                    for doc_id, score in scores.items()
                    if score >= min_score
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:top_k]

            results: list[BM25SearchResult] = []
            for rank_idx, (doc_id, score) in enumerate(ranked_items, start=1):
                doc = self._documents[doc_id]
                snippet = doc.content[:160] + ("..." if len(doc.content) > 160 else "")
                results.append(
                    BM25SearchResult(
                        doc_id=doc_id,
                        score=round(score, 4),
                        rank=rank_idx,
                        snippet=snippet,
                    )
                )

            return tuple(results)

    @property
    def total_documents(self) -> int:
        """Total number of documents currently indexed."""
        with self._lock:
            return len(self._documents)
