"""RAG & Memory retrieval quality assertion engine.

[INPUT]
- protocols::RetrievalAssertion (POS: assertion configuration for retrieval quality)
- protocols::RetrievalHit (POS: raw or collapsed retrieval hit data)

[OUTPUT]
- CollapsedHit: deduplicated hit identity with effective rank and aggregated bodies
- split_header_and_body(): splits markdown/yaml metadata headers from chunk body
- collapse_retrieval_hits(): collapses duplicate chunks from same document to distinct ranks
- evaluate_retrieval_assertions(): evaluates retrieval recall, deep body spans, and duplication

[POS]
Provides deterministic, zero-LLM-cost verification of agent retrieval quality,
deep body span reachability (Head vs Tail penetration), and source diversity.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.eval.protocols import RetrievalAssertion


@dataclass(frozen=True, slots=True)
class CollapsedHit:
    """Distinct document identity resulting from hit collapsing."""

    identity: str
    effective_rank: int
    first_slot: int
    bodies: tuple[str, ...]
    doc_id: str | None = None
    source_path: str | None = None


_HEADER_SEPARATOR_PATTERN = re.compile(r"^---\s*$", re.MULTILINE)
_HEADER_TITLE_PREFIX = re.compile(r"^(#\s+|Linear\s+[A-Z0-9]+|Repo:|Source:|DocID:|Commit:|Blob:)", re.IGNORECASE)


def normalize_retrieval_text(text: str) -> str:
    """Normalize text for invariant span matching (lowercase, collapsed whitespace, punctuation stripped)."""
    text = text.lower()
    text = re.sub(r"[`*_~#\[\]()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_header_and_body(text: str) -> tuple[str, str]:
    """Split metadata header (YAML frontmatter / Markdown title block) from actual body content."""
    lines = text.splitlines()
    if not lines:
        return "", ""

    body_start_idx = 0
    header_lines: list[str] = []

    # Check YAML frontmatter (--- ... ---)
    if lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start_idx = i + 1
                header_lines = lines[:body_start_idx]
                break
    else:
        # Check leading header metadata lines
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if _HEADER_TITLE_PREFIX.match(stripped):
                header_lines.append(line)
                body_start_idx = i + 1
            else:
                break

    header = "\n".join(header_lines)
    body = "\n".join(lines[body_start_idx:]).strip()
    return header, body if body else text


def collapse_retrieval_hits(hits: list[dict[str, Any] | Any]) -> list[CollapsedHit]:
    """Collapse ranked hits to distinct document identities, preserving the first occurrence rank.

    Multiple chunks from the same document contribute their bodies to the primary hit
    without inflating the effective rank count or crowding out other sources.
    """
    collapsed: list[CollapsedHit] = []
    seen: dict[str, int] = {}

    for slot, hit in enumerate(hits, start=1):
        if isinstance(hit, dict):
            doc_id = str(hit.get("doc_id") or hit.get("id") or hit.get("document_id") or "")
            source_path = str(hit.get("source_path") or hit.get("file_path") or "")
            blob_id = str(hit.get("blob_id") or hit.get("blob_sha") or "")
            text = str(hit.get("content") or hit.get("text") or hit.get("body") or "")
        else:
            doc_id = str(getattr(hit, "doc_id", "") or getattr(hit, "id", "") or "")
            source_path = str(getattr(hit, "source_path", "") or getattr(hit, "file_path", "") or "")
            blob_id = str(getattr(hit, "blob_id", "") or "")
            text = str(getattr(hit, "content", "") or getattr(hit, "text", "") or "")

        identity = source_path or doc_id or blob_id
        if not identity:
            identity = f"text:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"

        _, body = split_header_and_body(text)

        if identity in seen:
            idx = seen[identity]
            existing = collapsed[idx]
            collapsed[idx] = CollapsedHit(
                identity=existing.identity,
                effective_rank=existing.effective_rank,
                first_slot=existing.first_slot,
                bodies=(*existing.bodies, body),
                doc_id=existing.doc_id,
                source_path=existing.source_path,
            )
        else:
            seen[identity] = len(collapsed)
            collapsed.append(
                CollapsedHit(
                    identity=identity,
                    effective_rank=len(collapsed) + 1,
                    first_slot=slot,
                    bodies=(body,),
                    doc_id=doc_id if doc_id else None,
                    source_path=source_path if source_path else None,
                )
            )

    return collapsed


def evaluate_retrieval_assertions(
    assertions: list[RetrievalAssertion],
    retrieved_hits: list[dict[str, Any] | Any],
    *,
    scores_out: dict[str, float] | None = None,
) -> tuple[bool | None, str | None]:
    """Evaluate retrieval assertions against actual retrieved hits.

    Args:
        assertions: List of RetrievalAssertion specifications.
        retrieved_hits: Raw retrieved hits (list of dicts or objects).
        scores_out: Optional mutable dictionary to record numerical diagnostic scores.

    Returns:
        (passed, details) where passed is None if no assertions provided.
    """
    if not assertions:
        return None, None

    if not retrieved_hits:
        return False, "Retrieval assertion failed: No hits retrieved."

    collapsed = collapse_retrieval_hits(retrieved_hits)
    total_raw_hits = len(retrieved_hits)
    distinct_sources = len(collapsed)
    duplicate_count = max(0, total_raw_hits - distinct_sources)
    duplicate_rate = duplicate_count / total_raw_hits if total_raw_hits > 0 else 0.0

    if scores_out is not None:
        scores_out["total_raw_hits"] = float(total_raw_hits)
        scores_out["distinct_sources"] = float(distinct_sources)
        scores_out["duplicate_rate"] = round(duplicate_rate, 4)

    for assertion in assertions:
        eval_hits = retrieved_hits[: assertion.top_k]
        eval_collapsed = collapse_retrieval_hits(eval_hits)

        # 1. Distinct sources check
        if assertion.min_distinct_sources is not None and len(eval_collapsed) < assertion.min_distinct_sources:
            return (
                False,
                f"Retrieval assertion failed: distinct sources {len(eval_collapsed)} < min {assertion.min_distinct_sources}",
            )

        # 2. Duplicate rate check
        eval_dup_rate = max(0, len(eval_hits) - len(eval_collapsed)) / len(eval_hits) if eval_hits else 0.0
        if assertion.max_duplicate_rate is not None and eval_dup_rate > assertion.max_duplicate_rate:
            return (
                False,
                f"Retrieval assertion failed: duplicate rate {eval_dup_rate:.2f} > max {assertion.max_duplicate_rate:.2f}",
            )

        # 3. Expected doc_ids check
        if assertion.expected_doc_ids:
            found_doc_ids = {h.doc_id for h in eval_collapsed if h.doc_id}
            missing_ids = set(assertion.expected_doc_ids) - found_doc_ids
            if missing_ids:
                return (
                    False,
                    f"Retrieval assertion failed: missing expected doc_ids {sorted(missing_ids)} in top-{assertion.top_k}",
                )

        # 4. Expected spans (Head/Tail deep body verification)
        if assertion.expected_spans:
            all_body_text = " ".join(
                normalize_retrieval_text(b) for h in eval_collapsed for b in h.bodies
            )
            matched_spans: list[str] = []
            missing_spans: list[str] = []
            for span in assertion.expected_spans:
                norm_span = normalize_retrieval_text(span)
                if norm_span in all_body_text:
                    matched_spans.append(span)
                else:
                    missing_spans.append(span)

            span_recall = len(matched_spans) / len(assertion.expected_spans)
            if scores_out is not None:
                scores_out["span_recall"] = round(span_recall, 4)

            if span_recall < assertion.min_recall:
                return (
                    False,
                    f"Retrieval assertion failed: span recall {span_recall:.2f} < min {assertion.min_recall:.2f}. "
                    f"Missing: {missing_spans[:2]}",
                )

    return True, f"All retrieval assertions passed (distinct_sources={distinct_sources}, dup_rate={duplicate_rate:.2f})"
