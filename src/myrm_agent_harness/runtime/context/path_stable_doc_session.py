"""File-Path SHA-256 Stable Document Session Binding Hub.

Provides deterministic session derivation based on canonical file paths,
manages cross-turn incremental diff proposals and parsed chunk caches,
and ensures strict isolation across disparate document workflows.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Sequence
from threading import RLock

from myrm_agent_harness.runtime.context.path_stable_doc_session_types import (
    DocChunkCacheEntry,
    DocDiffProposalEntry,
    DocSessionBindingInfo,
    DocSessionContinuityContext,
)

__all__ = [
    "DocChunkCacheEntry",
    "DocDiffProposalEntry",
    "DocSessionBindingInfo",
    "DocSessionContinuityContext",
    "PathStableDocSessionHub",
]


class PathStableDocSessionHub:
    """Coordinates stable document session derivation, diff continuity, and cache retention."""

    def __init__(self) -> None:
        self._lock = RLock()
        # session_id -> DocSessionBindingInfo
        self._bindings: dict[str, DocSessionBindingInfo] = {}
        # canonical_path -> session_id
        self._path_to_session: dict[str, str] = {}
        # session_id -> list[DocDiffProposalEntry]
        self._proposals: dict[str, list[DocDiffProposalEntry]] = {}
        # session_id -> dict[chunk_id, DocChunkCacheEntry]
        self._chunk_caches: dict[str, dict[str, DocChunkCacheEntry]] = {}

    @classmethod
    def canonicalize_path(cls, file_path: str, base_dir: str | None = None) -> str:
        """Converts raw or relative file paths into standardized POSIX-style canonical paths."""
        stripped = file_path.strip()
        if base_dir and not os.path.isabs(stripped):
            combined = os.path.join(base_dir, stripped)
        else:
            combined = stripped
        norm = os.path.abspath(os.path.normpath(combined))
        # Standardize path separators
        return norm.replace("\\", "/")

    @classmethod
    def derive_session_id(cls, file_path: str, base_dir: str | None = None) -> str:
        """Generates deterministic SHA-256 stable session identifier from canonical path."""
        canon = cls.canonicalize_path(file_path, base_dir)
        sha_digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
        raw_basename = os.path.basename(canon)
        sanitized_slug = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", raw_basename)[:24]
        return f"doc-sess-{sanitized_slug}-{sha_digest}"

    def get_or_create_binding(
        self,
        file_path: str,
        base_dir: str | None = None,
    ) -> DocSessionBindingInfo:
        """Retrieves or registers a deterministic binding for the given document path."""
        canonical = self.canonicalize_path(file_path, base_dir)
        session_id = self.derive_session_id(canonical)
        now = time.time()

        with self._lock:
            if session_id in self._bindings:
                existing = self._bindings[session_id]
                updated = DocSessionBindingInfo(
                    file_path=file_path,
                    canonical_path=canonical,
                    session_id=session_id,
                    doc_basename=existing.doc_basename,
                    created_at=existing.created_at,
                    last_accessed_at=now,
                )
                self._bindings[session_id] = updated
                return updated

            binding = DocSessionBindingInfo(
                file_path=file_path,
                canonical_path=canonical,
                session_id=session_id,
                doc_basename=os.path.basename(canonical),
                created_at=now,
                last_accessed_at=now,
            )
            self._bindings[session_id] = binding
            self._path_to_session[canonical] = session_id
            self._proposals[session_id] = []
            self._chunk_caches[session_id] = {}
            return binding

    def record_diff_proposal(
        self,
        *,
        session_id: str,
        turn_index: int,
        target_section: str,
        summary: str,
        proposal_id: str | None = None,
    ) -> DocDiffProposalEntry:
        """Records an incremental diff or patch proposal for cross-turn auditability."""
        with self._lock:
            if session_id not in self._bindings:
                raise KeyError(f"Document session '{session_id}' not found.")

            pid = proposal_id or f"prop-{turn_index}-{len(self._proposals[session_id]) + 1}"
            entry = DocDiffProposalEntry(
                proposal_id=pid,
                turn_index=turn_index,
                target_section=target_section,
                summary=summary,
                is_applied=False,
                is_rejected=False,
                created_at=time.time(),
            )
            self._proposals[session_id].append(entry)
            return entry

    def mark_proposal_status(
        self,
        *,
        session_id: str,
        proposal_id: str,
        applied: bool,
    ) -> None:
        """Updates acceptance status for a specific diff proposal."""
        with self._lock:
            if session_id not in self._proposals:
                raise KeyError(f"Document session '{session_id}' not found.")

            entries = self._proposals[session_id]
            for idx, entry in enumerate(entries):
                if entry.proposal_id == proposal_id:
                    updated = DocDiffProposalEntry(
                        proposal_id=entry.proposal_id,
                        turn_index=entry.turn_index,
                        target_section=entry.target_section,
                        summary=entry.summary,
                        is_applied=applied,
                        is_rejected=not applied,
                        created_at=entry.created_at,
                    )
                    entries[idx] = updated
                    return
            raise KeyError(f"Proposal '{proposal_id}' not found in session '{session_id}'.")

    def cache_chunks(
        self,
        session_id: str,
        chunks: Sequence[DocChunkCacheEntry],
    ) -> None:
        """Stores parsed document chunks to prevent redundant re-parsing of large files."""
        with self._lock:
            if session_id not in self._bindings:
                raise KeyError(f"Document session '{session_id}' not found.")

            cache_map = self._chunk_caches[session_id]
            for chunk in chunks:
                cache_map[chunk.chunk_id] = chunk

    def get_cached_chunks(self, session_id: str) -> tuple[DocChunkCacheEntry, ...]:
        """Returns all cached document chunks for the session."""
        with self._lock:
            if session_id not in self._chunk_caches:
                return ()
            return tuple(self._chunk_caches[session_id].values())

    def generate_continuity_context(self, session_id: str) -> DocSessionContinuityContext:
        """Synthesizes structured XML continuity preamble for next agent turn."""
        with self._lock:
            if session_id not in self._bindings:
                raise KeyError(f"Document session '{session_id}' not found.")

            binding = self._bindings[session_id]
            proposals = self._proposals[session_id]
            chunks = list(self._chunk_caches[session_id].values())

            applied_count = sum(1 for p in proposals if p.is_applied)
            active_ids = tuple(p.proposal_id for p in proposals if not p.is_rejected)

            xml_lines: list[str] = [
                f'<document_session_continuity session_id="{session_id}" file="{binding.canonical_path}">',
                f'  <summary total_proposals="{len(proposals)}" applied="{applied_count}" cached_chunks="{len(chunks)}" />',
            ]

            if proposals:
                xml_lines.append("  <diff_proposals_history>")
                for p in proposals:
                    status = "APPLIED" if p.is_applied else ("REJECTED" if p.is_rejected else "PENDING")
                    xml_lines.append(
                        f'    <proposal id="{p.proposal_id}" turn="{p.turn_index}" section="{p.target_section}" status="{status}">'
                    )
                    xml_lines.append(f"      {p.summary}")
                    xml_lines.append("    </proposal>")
                xml_lines.append("  </diff_proposals_history>")

            if chunks:
                xml_lines.append("  <cached_document_sections>")
                for c in chunks:
                    xml_lines.append(
                        f'    <section id="{c.chunk_id}" title="{c.section_title}" tokens="{c.token_estimate}" />'
                    )
                xml_lines.append("  </cached_document_sections>")

            xml_lines.append("</document_session_continuity>")
            xml_text = "\n".join(xml_lines)

            return DocSessionContinuityContext(
                session_id=session_id,
                canonical_path=binding.canonical_path,
                total_proposals=len(proposals),
                applied_proposals=applied_count,
                cached_chunks_count=len(chunks),
                context_summary_xml=xml_text,
                active_proposal_ids=active_ids,
            )

    def check_multi_doc_isolation(self, session_id_a: str, session_id_b: str) -> bool:
        """Confirms that two sessions bind to separate canonical documents (pure isolation)."""
        with self._lock:
            binding_a = self._bindings.get(session_id_a)
            binding_b = self._bindings.get(session_id_b)
            if not binding_a or not binding_b:
                return session_id_a != session_id_b
            return binding_a.canonical_path != binding_b.canonical_path
