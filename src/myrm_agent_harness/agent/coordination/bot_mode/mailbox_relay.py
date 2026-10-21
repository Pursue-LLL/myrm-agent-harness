"""Thread-safe mailbox relay for bot-to-bot messaging and @mention dispatch (Item 33).

Provides direct asynchronous message delivery between AI colleagues,
automated @mention text parsing, and unread message tracking.

[INPUT]
- __future__
- logging
- re
- threading
- uuid
- roster

[OUTPUT]
- logger
- MENTION_REGEX
- InterBotMailboxRelay

[POS]
Thread-safe mailbox relay for bot-to-bot messaging and @mention dispatch (Item 33).
"""

from __future__ import annotations

import logging
import re
import threading
import uuid

from .roster import NamedBotRoster
from .types import (
    BotMessage,
    MentionDispatchResult,
    MessagePriority,
    ScalarValue,
)

logger = logging.getLogger(__name__)

# Regex for parsing @mentions (e.g. @code_reviewer, @tester-01)
MENTION_REGEX = re.compile(r"@([a-zA-Z0-9_\-]+)")


class InterBotMailboxRelay:
    """Inter-bot direct message relay and @mention dispatch router."""

    def __init__(self, roster: NamedBotRoster | None = None) -> None:
        self._lock = threading.Lock()
        self._roster = roster or NamedBotRoster()
        self._inboxes: dict[str, list[BotMessage]] = {}  # bot_id -> messages
        self._outboxes: dict[str, list[BotMessage]] = {}  # bot_id -> messages

    @property
    def roster(self) -> NamedBotRoster:
        return self._roster

    def send_message(
        self,
        from_bot: str,
        to_bot: str,
        subject: str,
        body: str,
        priority: MessagePriority = MessagePriority.NORMAL,
        task_payload: dict[str, ScalarValue] | None = None,
        thread_id: str | None = None,
    ) -> BotMessage:
        """Deliver a direct message from one bot to another."""
        # Resolve target recipient
        target_profile = self._roster.resolve_mention(to_bot)
        if not target_profile:
            raise ValueError(f"Target bot recipient '{to_bot}' is not registered in the roster")

        # Resolve sender profile (or fallback to identifier string)
        sender_profile = self._roster.resolve_mention(from_bot)
        sender_id = sender_profile.bot_id if sender_profile else from_bot

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        tid = thread_id or f"thread_{uuid.uuid4().hex[:8]}"

        message = BotMessage(
            message_id=msg_id,
            from_bot=sender_profile.handle if sender_profile else sender_id,
            to_bot=target_profile.handle,
            thread_id=tid,
            subject=subject,
            body=body,
            priority=priority,
            task_payload=dict(task_payload or {}),
            is_read=False,
        )

        with self._lock:
            # Deliver to target inbox
            target_id = target_profile.bot_id
            if target_id not in self._inboxes:
                self._inboxes[target_id] = []
            self._inboxes[target_id].append(message)

            # Record in sender outbox
            if sender_id not in self._outboxes:
                self._outboxes[sender_id] = []
            self._outboxes[sender_id].append(message)

        logger.info(
            "Delivered message '%s' from '%s' to '%s' (thread: %s)",
            msg_id,
            from_bot,
            target_profile.handle,
            tid,
        )
        return message

    def dispatch_mentions(
        self,
        text: str,
        from_bot: str,
        thread_id: str | None = None,
        task_payload: dict[str, ScalarValue] | None = None,
    ) -> list[MentionDispatchResult]:
        """Scan text for @mentions, resolve each bot, and auto-deliver the message to their inbox."""
        matches = MENTION_REGEX.findall(text)
        results: list[MentionDispatchResult] = []

        if not matches:
            return results

        # Deduplicate matched handles preserving order
        unique_handles = list(dict.fromkeys(matches))

        for raw_handle in unique_handles:
            handle_with_at = f"@{raw_handle}"
            target_bot = self._roster.get_bot_by_handle(handle_with_at)

            if not target_bot:
                results.append(
                    MentionDispatchResult(
                        dispatched=False,
                        target_bot_id=None,
                        target_handle=handle_with_at,
                        message_id=None,
                        note=f"Handle '{handle_with_at}' not found in active bot roster",
                    )
                )
                continue

            try:
                msg = self.send_message(
                    from_bot=from_bot,
                    to_bot=target_bot.handle,
                    subject=f"Mention notification from {from_bot}",
                    body=text,
                    priority=MessagePriority.NORMAL,
                    task_payload=task_payload,
                    thread_id=thread_id,
                )
                results.append(
                    MentionDispatchResult(
                        dispatched=True,
                        target_bot_id=target_bot.bot_id,
                        target_handle=target_bot.handle,
                        message_id=msg.message_id,
                        note=f"Successfully dispatched mention to {target_bot.display_name} ({target_bot.handle})",
                    )
                )
            except Exception as err:
                results.append(
                    MentionDispatchResult(
                        dispatched=False,
                        target_bot_id=target_bot.bot_id,
                        target_handle=target_bot.handle,
                        message_id=None,
                        note=f"Failed to dispatch to {target_bot.handle}: {err}",
                    )
                )

        return results

    def get_inbox(self, bot_id: str, unread_only: bool = False) -> tuple[BotMessage, ...]:
        """Retrieve incoming messages for a bot."""
        # Resolve to bot_id if handle passed
        profile = self._roster.resolve_mention(bot_id)
        effective_id = profile.bot_id if profile else bot_id

        with self._lock:
            msgs = list(self._inboxes.get(effective_id, []))

        if unread_only:
            msgs = [m for m in msgs if not m.is_read]
        return tuple(msgs)

    def get_outbox(self, bot_id: str) -> tuple[BotMessage, ...]:
        """Retrieve outgoing messages sent by a bot."""
        profile = self._roster.resolve_mention(bot_id)
        effective_id = profile.bot_id if profile else bot_id

        with self._lock:
            return tuple(self._outboxes.get(effective_id, []))

    def mark_as_read(self, bot_id: str, message_ids: tuple[str, ...]) -> int:
        """Mark specific messages in the bot's inbox as read."""
        profile = self._roster.resolve_mention(bot_id)
        effective_id = profile.bot_id if profile else bot_id

        target_set = set(message_ids)
        updated_count = 0

        with self._lock:
            inbox = self._inboxes.get(effective_id, [])
            for idx, msg in enumerate(inbox):
                if msg.message_id in target_set and not msg.is_read:
                    inbox[idx] = BotMessage(
                        message_id=msg.message_id,
                        from_bot=msg.from_bot,
                        to_bot=msg.to_bot,
                        thread_id=msg.thread_id,
                        subject=msg.subject,
                        body=msg.body,
                        priority=msg.priority,
                        task_payload=msg.task_payload,
                        is_read=True,
                        timestamp=msg.timestamp,
                    )
                    updated_count += 1

        return updated_count

    def get_unread_count(self, bot_id: str) -> int:
        """Count pending unread messages in the bot's inbox."""
        return len(self.get_inbox(bot_id, unread_only=True))

    def clear_mailbox(self, bot_id: str) -> None:
        """Clear both inbox and outbox for a bot."""
        profile = self._roster.resolve_mention(bot_id)
        effective_id = profile.bot_id if profile else bot_id

        with self._lock:
            self._inboxes.pop(effective_id, None)
            self._outboxes.pop(effective_id, None)

    def reset_all(self) -> None:
        """Clear all active mailbox data."""
        with self._lock:
            self._inboxes.clear()
            self._outboxes.clear()
