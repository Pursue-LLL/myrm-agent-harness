"""Gateway orchestrating workspace file mutation events and session context invalidation.

[INPUT]
- agent.context_management.file_watch.file_watch_types::AutoIngressResult, ContextInvalidationNudge,
  DocumentFreshnessStatus, FileFingerprint, FileMutationKind, SessionDocumentBinding (POS: Types and models
  for file watch.)

[OUTPUT]
- WorkspaceFileWatchContextGateway: Gateway orchestrating workspace file mutation events and session context
  invalidation.

[POS]
Gateway orchestrating workspace file mutation events and session context invalidation.
"""

# ============================================================================
# Workspace File Watch Context Invalidation & Auto-Ingress Gateway (Item 165)
# Real-time synchronization between external file system mutations and in-session
# document cache, passive cache invalidation, ambient nudges, and auto-ingress.
# ============================================================================

from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable

from .file_watch_types import (
    AutoIngressResult,
    ContextInvalidationNudge,
    DocumentFreshnessStatus,
    FileFingerprint,
    FileMutationKind,
    SessionDocumentBinding,
)

logger = logging.getLogger(__name__)


def _compute_sha256(content: str) -> str:
    """Compute deterministic SHA-256 hex digest for string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_path(path: str) -> str:
    """Normalize file path to POSIX canonical style."""
    return os.path.normpath(path).replace("\\", "/")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceFileWatchContextGateway:
    """Gateway orchestrating workspace file mutation events and session context invalidation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # session_id -> {normalized_path: SessionDocumentBinding}
        self._bindings: dict[str, dict[str, SessionDocumentBinding]] = {}
        # normalized_path -> set of session_ids
        self._file_sessions: dict[str, set[str]] = {}
        # session_id -> list of pending ContextInvalidationNudge
        self._pending_nudges: dict[str, list[ContextInvalidationNudge]] = {}

    def bind_session_document(
        self,
        session_id: str,
        path: str,
        content: str,
        mtime_ns: int = 0,
    ) -> SessionDocumentBinding:
        """Bind or refresh a workspace document inside session context cache."""
        norm_path = _normalize_path(path)
        sha256_hash = _compute_sha256(content)
        byte_size = len(content.encode("utf-8"))

        fingerprint = FileFingerprint(
            path=norm_path,
            sha256=sha256_hash,
            mtime_ns=mtime_ns,
            byte_size=byte_size,
        )

        binding = SessionDocumentBinding(
            session_id=session_id,
            path=norm_path,
            fingerprint=fingerprint,
            cached_content=content,
            status=DocumentFreshnessStatus.FRESH,
            cached_at_iso=_utc_now_iso(),
        )

        with self._lock:
            session_dict = self._bindings.setdefault(session_id, {})
            session_dict[norm_path] = binding
            self._file_sessions.setdefault(norm_path, set()).add(session_id)

        logger.info(
            "Bound document '%s' to session '%s' (sha256=%s, bytes=%d)",
            norm_path,
            session_id,
            sha256_hash[:8],
            byte_size,
        )
        return binding

    def notify_workspace_mutation(
        self,
        path: str,
        mutation_kind: FileMutationKind,
        new_content: str | None = None,
        mtime_ns: int = 0,
    ) -> tuple[ContextInvalidationNudge, ...]:
        """Process external file mutation event, mark bound session caches stale, and generate nudges."""
        norm_path = _normalize_path(path)

        with self._lock:
            affected_sessions = list(self._file_sessions.get(norm_path, set()))
            if not affected_sessions:
                return ()

            nudges: list[ContextInvalidationNudge] = []
            new_sha256 = _compute_sha256(new_content) if new_content is not None else ""

            for sess_id in affected_sessions:
                sess_bindings = self._bindings.get(sess_id, {})
                old_binding = sess_bindings.get(norm_path)
                if old_binding is None:
                    continue

                old_sha = old_binding.fingerprint.sha256

                # Check if modification is a no-op identical edit
                if (
                    mutation_kind == FileMutationKind.MODIFIED
                    and new_content is not None
                    and old_sha == new_sha256
                ):
                    continue

                if mutation_kind == FileMutationKind.DELETED:
                    new_status = DocumentFreshnessStatus.EVICTED
                    msg = f"本地文件《{os.path.basename(norm_path)}》已被删除，对应会话缓存已置为失效。"
                else:
                    new_status = DocumentFreshnessStatus.STALE
                    msg = f"本地文件《{os.path.basename(norm_path)}》已在外部更新，已置脏缓存并将自动刷新。"

                # Update binding status to stale/evicted
                updated_binding = SessionDocumentBinding(
                    session_id=old_binding.session_id,
                    path=old_binding.path,
                    fingerprint=old_binding.fingerprint,
                    cached_content=old_binding.cached_content,
                    status=new_status,
                    cached_at_iso=old_binding.cached_at_iso,
                )
                sess_bindings[norm_path] = updated_binding

                nudge = ContextInvalidationNudge(
                    session_id=sess_id,
                    path=norm_path,
                    mutation_kind=mutation_kind,
                    old_sha256=old_sha,
                    new_sha256=new_sha256 or "unknown",
                    nudge_message=msg,
                    timestamp_iso=_utc_now_iso(),
                )
                nudges.append(nudge)
                self._pending_nudges.setdefault(sess_id, []).append(nudge)

            logger.info(
                "Processed mutation '%s' on '%s': invalidated in %d sessions",
                mutation_kind.value,
                norm_path,
                len(nudges),
            )
            return tuple(nudges)

    def consume_pending_nudges(self, session_id: str) -> tuple[ContextInvalidationNudge, ...]:
        """Consume and clear all pending ambient nudges for the session."""
        with self._lock:
            nudges = self._pending_nudges.pop(session_id, [])
            return tuple(nudges)

    def auto_ingress_stale_documents(
        self,
        session_id: str,
        file_reader: Callable[[str], str],
    ) -> tuple[AutoIngressResult, ...]:
        """Incrementally re-ingest all stale documents bound to session using external reader."""
        with self._lock:
            sess_bindings = self._bindings.get(session_id, {})
            if not sess_bindings:
                return ()

            stale_paths = [
                p
                for p, b in sess_bindings.items()
                if b.status == DocumentFreshnessStatus.STALE
            ]

            results: list[AutoIngressResult] = []
            now_iso = _utc_now_iso()

            for path in stale_paths:
                old_binding = sess_bindings[path]
                try:
                    fresh_content = file_reader(path)
                except Exception as exc:
                    logger.warning("Failed to auto-ingress '%s' in session '%s': %s", path, session_id, exc)
                    continue

                updated_sha256 = _compute_sha256(fresh_content)
                old_bytes = old_binding.fingerprint.byte_size
                new_bytes = len(fresh_content.encode("utf-8"))
                byte_delta = new_bytes - old_bytes

                new_fingerprint = FileFingerprint(
                    path=path,
                    sha256=updated_sha256,
                    mtime_ns=int(datetime.now(timezone.utc).timestamp() * 1e9),
                    byte_size=new_bytes,
                )

                refreshed_binding = SessionDocumentBinding(
                    session_id=session_id,
                    path=path,
                    fingerprint=new_fingerprint,
                    cached_content=fresh_content,
                    status=DocumentFreshnessStatus.RE_INDEXED,
                    cached_at_iso=now_iso,
                )
                sess_bindings[path] = refreshed_binding

                results.append(
                    AutoIngressResult(
                        session_id=session_id,
                        path=path,
                        previous_sha256=old_binding.fingerprint.sha256,
                        updated_sha256=updated_sha256,
                        byte_delta=byte_delta,
                        refreshed_at_iso=now_iso,
                        status=DocumentFreshnessStatus.RE_INDEXED,
                    )
                )

            logger.info(
                "Auto-ingressed %d stale documents for session '%s'",
                len(results),
                session_id,
            )
            return tuple(results)

    def get_session_binding(self, session_id: str, path: str) -> SessionDocumentBinding | None:
        """Fetch current document binding state for a specific session."""
        norm_path = _normalize_path(path)
        with self._lock:
            return self._bindings.get(session_id, {}).get(norm_path)

    def evict_session_binding(self, session_id: str, path: str) -> bool:
        """Explicitly evict document binding from session."""
        norm_path = _normalize_path(path)
        with self._lock:
            sess_bindings = self._bindings.get(session_id)
            if not sess_bindings or norm_path not in sess_bindings:
                return False

            del sess_bindings[norm_path]
            sessions_for_file = self._file_sessions.get(norm_path)
            if sessions_for_file:
                sessions_for_file.discard(session_id)
                if not sessions_for_file:
                    self._file_sessions.pop(norm_path, None)

            return True
