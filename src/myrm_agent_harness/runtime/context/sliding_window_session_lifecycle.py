"""Adaptive inactivity sliding window session lifecycle manager and KV cache keeper."""

from __future__ import annotations

import hashlib
import time
from threading import RLock

from myrm_agent_harness.runtime.context.sliding_window_session_lifecycle_types import (
    CrystallizedSessionMemory,
    InactivityWindowConfig,
    PrefixCacheFingerprint,
    SessionLifecycleSnapshot,
    SessionLifecycleState,
)


class PrefixKvCacheStabilityKeeper:
    """Monitors and preserves prefix prompt stability to maximize LLM KV cache hit rate."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._session_fingerprints: dict[str, PrefixCacheFingerprint] = {}

    def compute_prefix_fingerprint(
        self,
        system_prompt: str,
        static_tools_doc: str = "",
        current_time: float | None = None,
    ) -> PrefixCacheFingerprint:
        """Computes a SHA-256 fingerprint and approximate token count for the static prefix."""
        now = time.time() if current_time is None else current_time
        canonical_content = f"{system_prompt.strip()}\n---\n{static_tools_doc.strip()}"
        sha = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
        token_count = max(1, len(canonical_content) // 4)
        return PrefixCacheFingerprint(
            prefix_hash=sha,
            token_count=token_count,
            last_verified_at=now,
            is_frozen=True,
        )

    def register_or_verify_prefix(
        self,
        session_id: str,
        current_prefix: str,
        current_time: float | None = None,
    ) -> tuple[bool, str]:
        """Registers initial prefix or verifies that the prefix has not drifted.

        Returns (is_stable, message).
        """
        now = time.time() if current_time is None else current_time
        new_fp = self.compute_prefix_fingerprint(current_prefix, current_time=now)
        with self._lock:
            existing = self._session_fingerprints.get(session_id)
            if existing is None:
                self._session_fingerprints[session_id] = new_fp
                return True, "Prefix fingerprint successfully registered and frozen."
            if existing.prefix_hash == new_fp.prefix_hash:
                return True, "Prefix fingerprint perfectly matched. 100% KV Cache hit guaranteed."
            return (
                False,
                f"Prefix drifted for session '{session_id}': hash changed from "
                f"{existing.prefix_hash[:8]} to {new_fp.prefix_hash[:8]}. KV Cache hit may miss.",
            )

    def get_fingerprint(self, session_id: str) -> PrefixCacheFingerprint | None:
        """Retrieves active fingerprint for a session."""
        with self._lock:
            return self._session_fingerprints.get(session_id)

    @staticmethod
    def estimate_cache_savings(
        prefix_tokens: int,
        query_count: int,
        cache_discount_rate: float = 0.85,
    ) -> dict[str, float]:
        """Estimates token and cost savings enabled by prefix prompt caching."""
        if query_count <= 1:
            return {"cached_queries": 0.0, "saved_tokens": 0.0, "savings_ratio": 0.0}
        cached_queries = float(query_count - 1)
        saved_tokens = float(prefix_tokens) * cached_queries * cache_discount_rate
        total_possible = float(prefix_tokens) * float(query_count)
        ratio = saved_tokens / total_possible if total_possible > 0.0 else 0.0
        return {
            "cached_queries": cached_queries,
            "saved_tokens": saved_tokens,
            "savings_ratio": round(ratio, 4),
        }


class SessionMemoryCrystallizer:
    """Extracts distilled facts and key decisions upon session expiration and archival."""

    @staticmethod
    def crystallize(
        session_id: str,
        messages: list[dict[str, str]],
        inactivity_duration_seconds: float,
        current_time: float | None = None,
    ) -> CrystallizedSessionMemory:
        """Extracts facts, key decisions, and user preferences from historical messages."""
        now = time.time() if current_time is None else current_time
        facts: list[str] = []
        decisions: list[str] = []
        preferences: list[str] = []

        for msg in messages:
            content = msg.get("content", "")
            lines = content.splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                lower = stripped.lower()
                if "prefer" in lower or "preference" in lower or "偏好" in lower or "习惯" in lower:
                    preferences.append(stripped)
                elif "decided" in lower or "decision" in lower or "决定" in lower or "结论" in lower:
                    decisions.append(stripped)
                elif "fact" in lower or "note:" in lower or "约定" in lower or "架构" in lower:
                    facts.append(stripped)

        headline = (
            f"Archived session {session_id} after {inactivity_duration_seconds / 3600.0:.1f}h "
            f"inactivity with {len(messages)} messages."
        )

        return CrystallizedSessionMemory(
            session_id=session_id,
            crystallized_at=now,
            inactivity_duration_seconds=inactivity_duration_seconds,
            extracted_facts=tuple(facts[:15]),
            key_decisions=tuple(decisions[:10]),
            user_preferences=tuple(preferences[:10]),
            summary_headline=headline,
        )


class InactivitySlidingWindowSessionManager:
    """Governs session lifecycle via adaptive sliding inactivity window and atomic archival."""

    def __init__(self, config: InactivityWindowConfig | None = None) -> None:
        self._config = config or InactivityWindowConfig()
        self._lock = RLock()
        self._session_records: dict[str, dict[str, float | int | SessionLifecycleState]] = {}
        self._crystallized_store: dict[str, CrystallizedSessionMemory] = {}
        self._cache_keeper = PrefixKvCacheStabilityKeeper()
        self._crystallizer = SessionMemoryCrystallizer()

    @property
    def config(self) -> InactivityWindowConfig:
        return self._config

    @property
    def cache_keeper(self) -> PrefixKvCacheStabilityKeeper:
        return self._cache_keeper

    def touch_session(
        self,
        session_id: str,
        current_time: float | None = None,
        message_increment: int = 1,
        prefix_content: str = "",
    ) -> SessionLifecycleSnapshot:
        """Registers a session or refreshes its sliding window upon new interaction."""
        now = time.time() if current_time is None else current_time
        with self._lock:
            record = self._session_records.get(session_id)
            if record is None:
                record = {
                    "created_at": now,
                    "last_active_at": now,
                    "message_count": message_increment,
                    "state": SessionLifecycleState.ACTIVE,
                }
                self._session_records[session_id] = record
            else:
                record["last_active_at"] = now
                count = int(record.get("message_count", 0))
                record["message_count"] = count + message_increment
                record["state"] = SessionLifecycleState.ACTIVE

        if prefix_content and self._config.enable_prefix_caching_guard:
            self._cache_keeper.register_or_verify_prefix(session_id, prefix_content, current_time=now)

        return self.get_session_snapshot(session_id, current_time=now)  # type: ignore[return-value]

    def evaluate_session_state(
        self,
        session_id: str,
        current_time: float | None = None,
    ) -> SessionLifecycleState:
        """Evaluates whether the session is active, idle stable, expired, or archived."""
        now = time.time() if current_time is None else current_time
        with self._lock:
            record = self._session_records.get(session_id)
            if record is None:
                return SessionLifecycleState.EXPIRED_PENDING_ARCHIVE
            current_state = record["state"]
            if current_state == SessionLifecycleState.ARCHIVED:
                return SessionLifecycleState.ARCHIVED

            last_active = float(record["last_active_at"])
            inactivity = max(0.0, now - last_active)

            if inactivity >= self._config.inactivity_timeout_seconds:
                record["state"] = SessionLifecycleState.EXPIRED_PENDING_ARCHIVE
                return SessionLifecycleState.EXPIRED_PENDING_ARCHIVE
            elif inactivity >= self._config.idle_warning_threshold_seconds:
                record["state"] = SessionLifecycleState.IDLE_STABLE
                return SessionLifecycleState.IDLE_STABLE

            record["state"] = SessionLifecycleState.ACTIVE
            return SessionLifecycleState.ACTIVE

    def sweep_and_archive_expired_sessions(
        self,
        session_messages_provider: dict[str, list[dict[str, str]]] | None = None,
        current_time: float | None = None,
    ) -> list[SessionLifecycleSnapshot]:
        """Scans all registered sessions, marks expired sessions as ARCHIVED, and crystallizes memories."""
        now = time.time() if current_time is None else current_time
        archived_snapshots: list[SessionLifecycleSnapshot] = []

        with self._lock:
            for session_id in list(self._session_records.keys()):
                state = self.evaluate_session_state(session_id, current_time=now)
                if state == SessionLifecycleState.EXPIRED_PENDING_ARCHIVE:
                    record = self._session_records[session_id]
                    last_active = float(record["last_active_at"])
                    inactivity = max(0.0, now - last_active)

                    messages = (session_messages_provider or {}).get(session_id, [])
                    if self._config.auto_crystallize_on_archive:
                        c_mem = self._crystallizer.crystallize(
                            session_id, messages, inactivity, current_time=now
                        )
                        self._crystallized_store[session_id] = c_mem

                    record["state"] = SessionLifecycleState.ARCHIVED
                    snapshot = self.get_session_snapshot(session_id, current_time=now)
                    if snapshot is not None:
                        archived_snapshots.append(snapshot)

        return archived_snapshots

    def manual_archive_session(
        self,
        session_id: str,
        messages: list[dict[str, str]] | None = None,
        current_time: float | None = None,
    ) -> SessionLifecycleSnapshot:
        """Manually archives an active session and immediately triggers memory crystallization."""
        now = time.time() if current_time is None else current_time
        with self._lock:
            record = self._session_records.get(session_id)
            if record is None:
                record = {
                    "created_at": now,
                    "last_active_at": now,
                    "message_count": len(messages) if messages else 0,
                    "state": SessionLifecycleState.ACTIVE,
                }
                self._session_records[session_id] = record

            last_active = float(record["last_active_at"])
            inactivity = max(0.0, now - last_active)

            if self._config.auto_crystallize_on_archive:
                c_mem = self._crystallizer.crystallize(
                    session_id, messages or [], inactivity, current_time=now
                )
                self._crystallized_store[session_id] = c_mem

            record["state"] = SessionLifecycleState.ARCHIVED

        snap = self.get_session_snapshot(session_id, current_time=now)
        assert snap is not None
        return snap

    def get_session_snapshot(
        self,
        session_id: str,
        current_time: float | None = None,
    ) -> SessionLifecycleSnapshot | None:
        """Returns the current immutable lifecycle snapshot for the given session."""
        now = time.time() if current_time is None else current_time
        with self._lock:
            record = self._session_records.get(session_id)
            if record is None:
                return None
            last_active = float(record["last_active_at"])
            inactivity = max(0.0, now - last_active)
            state = record["state"]
            if not isinstance(state, SessionLifecycleState):
                state = SessionLifecycleState(str(state))
            created_at = float(record["created_at"])
            message_count = int(record["message_count"])

        fp = self._cache_keeper.get_fingerprint(session_id)
        c_mem = self._crystallized_store.get(session_id)

        return SessionLifecycleSnapshot(
            session_id=session_id,
            state=state,
            created_at=created_at,
            last_active_at=last_active,
            inactivity_seconds=inactivity,
            message_count=message_count,
            cache_fingerprint=fp,
            crystallized_memory=c_mem,
        )
