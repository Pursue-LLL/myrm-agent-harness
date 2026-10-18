"""BM25 Sparse Encoding — hash-based sparse vectors for the mirror.

[INPUT]
- memory.protocols.vector::VectorDocument (POS: dense-path document layout)
- retriever.bm25_retrieval::preprocess_text (POS: shared CJK/latin tokenizer)
- toolkits.vector.base::SparsePoint (POS: sparse point model)

[OUTPUT]
- token_index: stable u31 token hash (zero-vocabulary, no term dictionary)
- content_to_sparse / query_to_sparse: token stream -> (indices, values)
- BM25_COLLECTION_SUFFIX / bm25_collection_for: sparse mirror collection naming
- doc_to_sparse_point: dense-path document -> mirrored sparse point

[POS]
Pure encoding layer of the persistent BM25 mirror: tokens are hashed
(crc32 & 0x7FFFFFFF), term frequency saturates via ``1 + ln(tf)``, and IDF
weighting happens server-side (Qdrant sparse scoring). No I/O lives here, so
the mirror's write and query paths share one canonical tokenization.
"""

from __future__ import annotations

import math
import zlib
from collections import Counter

from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.vector.base import SparsePoint

BM25_COLLECTION_SUFFIX = "_bm25"


def token_index(token: str) -> int:
    """Stable u31 token hash — zero vocabulary, no term dictionary to persist.

    crc32 over the utf-8 token keeps hashing allocation-light; collisions merge
    two rare terms' frequencies, a bounded-quality tradeoff standard for
    hash-based sparse retrieval.
    """
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def content_to_sparse(text: str) -> tuple[list[int], list[float]]:
    """Tokenize content into a saturated term-frequency sparse vector."""
    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import preprocess_text

    # dedupe=False keeps term frequencies (default dedupe would flatten tf to 1)
    frequencies = Counter(preprocess_text(text, dedupe=False))
    if not frequencies:
        return [], []
    pairs = sorted((token_index(token), 1.0 + math.log(count)) for token, count in frequencies.items())
    indices, values = zip(*pairs, strict=True)
    return list(indices), list(values)


def query_to_sparse(text: str) -> tuple[list[int], list[float]]:
    """Tokenize a query into uniform-weight sparse indices (no tf on query side)."""
    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import preprocess_text

    tokens = {t for t in preprocess_text(text) if t}
    if not tokens:
        return [], []
    indices = sorted(token_index(t) for t in tokens)
    return indices, [1.0] * len(indices)


def bm25_collection_for(collection: str) -> str:
    """Sparse mirror collection name for a dense collection."""
    return f"{collection}{BM25_COLLECTION_SUFFIX}"


def doc_to_sparse_point(doc: VectorDocument) -> SparsePoint:
    """Convert a dense-path document into its sparse mirror point.

    Payload stays identical to the dense upsert layout (same metadata and
    timestamps), so FilterDict semantics filter sparse results exactly like
    dense results.
    """
    indices, values = content_to_sparse(doc.content)
    return SparsePoint(
        id=doc.id,
        indices=indices,
        values=values,
        content=doc.content,
        metadata=dict(doc.metadata),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )
