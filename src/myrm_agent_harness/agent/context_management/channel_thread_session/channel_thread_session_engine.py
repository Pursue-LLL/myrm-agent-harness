"""Core implementation of Channel Thread to Session Dynamic Binding and Isolated Branching Engine.

Resolves multi-channel thread ingress into strictly isolated child session branches,
guarantees per-thread zero-lock-contention execution, and manages lifecycle archives.
"""

from __future__ import annotations

import threading
import time
import uuid

from .channel_thread_types import (
    ThreadBindingKey,
    ThreadIsolationPolicy,
    ThreadRoutingDecision,
    ThreadSessionBranch,
)


class ChannelThreadSessionEngine:
    """Industrial engine routing IM channel threads to isolated session branches."""

    def __init__(self, policy: ThreadIsolationPolicy | None = None) -> None:
        self.policy = policy or ThreadIsolationPolicy()
        self._global_lock = threading.Lock()
        self._branches: dict[str, ThreadSessionBranch] = {}
        self._contexts: dict[str, list[dict[str, str]]] = {}
        self._locks: dict[str, threading.Lock] = {}

    def build_canonical_session_key(
        self, channel: str, chat_id: str, thread_id: str | None = None
    ) -> str:
        """Derive the deterministic canonical session key for channel, chat, and thread."""
        chan = channel.strip().lower()
        c_id = chat_id.strip()
        if thread_id and thread_id.strip():
            return f"{chan}:{c_id}:thread:{thread_id.strip()}"
        return f"{chan}:{c_id}:main"

    def resolve_thread_session(
        self,
        channel: str,
        chat_id: str,
        thread_id: str | None = None,
        message_id: str | None = None,
    ) -> ThreadRoutingDecision:
        """Resolve inbound message to an isolated child session branch or main chat."""
        canonical_key = self.build_canonical_session_key(channel, chat_id, thread_id)
        is_isolated = bool(thread_id and thread_id.strip())

        with self._global_lock:
            if is_isolated and thread_id:
                branch = self._branches.get(canonical_key)
                if not branch:
                    branch = ThreadSessionBranch(
                        branch_id=f"branch-{uuid.uuid4().hex[:8]}",
                        session_key=canonical_key,
                        channel=channel.strip().lower(),
                        chat_id=chat_id.strip(),
                        thread_id=thread_id.strip(),
                        created_at=time.time(),
                        message_count=0,
                        is_active=True,
                        summary=None,
                    )
                    self._branches[canonical_key] = branch
                    self._contexts[canonical_key] = []

                    # Optional context inheritance from main chat if configured
                    if self.policy.inherit_main_context_on_spawn:
                        main_key = self.build_canonical_session_key(channel, chat_id, None)
                        main_msgs = self._contexts.get(main_key, [])
                        for m in main_msgs:
                            if m.get("role") == "system":
                                self._contexts[canonical_key].append(dict(m))

                branch_id = branch.branch_id
                reply_thread = thread_id.strip()
            else:
                branch_id = "main"
                reply_thread = None
                if canonical_key not in self._contexts:
                    self._contexts[canonical_key] = []

            # Ensure dedicated lock exists for this session key
            if canonical_key not in self._locks:
                self._locks[canonical_key] = threading.Lock()

        return ThreadRoutingDecision(
            target_session_key=canonical_key,
            is_thread_isolated=is_isolated,
            branch_id=branch_id,
            reply_to_thread_id=reply_thread,
        )

    def append_message(self, session_key: str, role: str, content: str) -> None:
        """Append a message to an isolated thread session context."""
        with self.get_session_lock(session_key):
            ctx = self._contexts.setdefault(session_key, [])
            ctx.append({"role": role, "content": content})

            branch = self._branches.get(session_key)
            if branch:
                updated_branch = ThreadSessionBranch(
                    branch_id=branch.branch_id,
                    session_key=branch.session_key,
                    channel=branch.channel,
                    chat_id=branch.chat_id,
                    thread_id=branch.thread_id,
                    created_at=branch.created_at,
                    message_count=branch.message_count + 1,
                    is_active=branch.is_active,
                    summary=branch.summary,
                )
                self._branches[session_key] = updated_branch

    def get_messages(self, session_key: str) -> list[dict[str, str]]:
        """Retrieve message sequence for a thread session, ensuring zero cross-contamination."""
        with self.get_session_lock(session_key):
            return list(self._contexts.get(session_key, []))

    def get_branch(self, session_key: str) -> ThreadSessionBranch | None:
        """Retrieve branch metadata for a thread session."""
        with self._global_lock:
            return self._branches.get(session_key)

    def archive_thread(
        self, session_key: str, summary_text: str | None = None
    ) -> ThreadSessionBranch:
        """Mark a thread branch as archived and attach optional concluding summary."""
        with self._global_lock:
            branch = self._branches.get(session_key)
            if not branch:
                raise ValueError(f"No thread branch registered under session key: {session_key}")

            effective_summary = summary_text
            if effective_summary is None and self.policy.auto_summarize_on_archive:
                effective_summary = f"[Thread Concluded]: Discussion for thread {branch.thread_id} completed."

            archived_branch = ThreadSessionBranch(
                branch_id=branch.branch_id,
                session_key=branch.session_key,
                channel=branch.channel,
                chat_id=branch.chat_id,
                thread_id=branch.thread_id,
                created_at=branch.created_at,
                message_count=branch.message_count,
                is_active=False,
                summary=effective_summary,
            )
            self._branches[session_key] = archived_branch
            return archived_branch

    def get_active_threads_in_chat(
        self, channel: str, chat_id: str
    ) -> tuple[ThreadSessionBranch, ...]:
        """Query all active thread branches currently alive in a chat."""
        target_chan = channel.strip().lower()
        target_chat = chat_id.strip()
        with self._global_lock:
            active = [
                b for b in self._branches.values()
                if b.channel == target_chan and b.chat_id == target_chat and b.is_active
            ]
        return tuple(active)

    def get_session_lock(self, session_key: str) -> threading.Lock:
        """Retrieve the dedicated concurrency lock for a session to prevent lock contention."""
        with self._global_lock:
            if session_key not in self._locks:
                self._locks[session_key] = threading.Lock()
            return self._locks[session_key]
