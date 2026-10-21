"""Durable Peer Mailbox with JSONL log persistence and cold recovery for Agent Teams.

[INPUT]
- .types::(DeliveryMode, TeamMessageSnapshot)
- myrm_agent_harness.infra.atomic_write::atomic_write

[OUTPUT]
- DurablePeerMailbox: peer messaging, quiet/waking delivery, cold recovery, FIFO drain, rate limiting

[POS]
Decentralized P2P message bus allowing durable team members to communicate
directly with transactional log replay safety.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.infra.atomic_write import atomic_write

from .types import DeliveryMode, TeamMessageSnapshot

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_DEFAULT_RATE_LIMIT_PER_SENDER = 30
_DEFAULT_RATE_LIMIT_WINDOW_SEC = 60.0
_MAX_JSONL_RECORDS = 2000


class DurablePeerMailbox:
    """Session-scoped durable peer mailbox with cold-replay recovery."""

    def __init__(
        self,
        team_id: str,
        workspace_path: str | None = None,
        rate_limit_per_sender: int = _DEFAULT_RATE_LIMIT_PER_SENDER,
        rate_limit_window_sec: float = _DEFAULT_RATE_LIMIT_WINDOW_SEC,
    ) -> None:
        self.team_id = team_id
        self.workspace_path = workspace_path
        self._rate_limit = rate_limit_per_sender
        self._rate_window = rate_limit_window_sec

        self._inboxes: dict[str, deque[TeamMessageSnapshot]] = {}
        self._sender_times: dict[str, deque[float]] = {}
        self._counter: int = 0
        self._log_path: Path | None = None

        if workspace_path:
            teams_dir = Path(workspace_path) / "teams" / team_id
            teams_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = teams_dir / "mailbox.jsonl"
            self.recover_from_disk()

    def _check_rate_limit(self, sender_id: str) -> bool:
        now = time.time()
        start = now - self._rate_window
        times = self._sender_times.setdefault(sender_id, deque())
        while times and times[0] <= start:
            times.popleft()
        if len(times) >= self._rate_limit:
            return False
        times.append(now)
        return True

    def send_peer_message(
        self,
        sender_id: str,
        sender_name: str,
        target_id: str,
        target_name: str,
        content: str,
        mode: DeliveryMode = DeliveryMode.QUIET,
    ) -> TeamMessageSnapshot:
        """Send a peer message to a teammate with rate limit and durable log."""
        if not self._check_rate_limit(sender_id):
            raise RuntimeError(
                f"Peer mailbox rate limit exceeded for sender {sender_name} ({sender_id})"
            )

        self._counter += 1
        msg_id = f"msg-{self.team_id}-{self._counter}"
        now = time.time()

        snapshot = TeamMessageSnapshot(
            id=msg_id,
            team_id=self.team_id,
            sender_id=sender_id,
            sender_name=sender_name,
            target_id=target_id,
            target_name=target_name,
            content=content,
            mode=mode,
            created_at=now,
            delivered=False,
        )

        inbox = self._inboxes.setdefault(target_id, deque())
        inbox.append(snapshot)
        self._append_log({"event": "queued", "message": snapshot.to_dict()})
        return snapshot

    def drain_inbox(self, target_id: str) -> list[TeamMessageSnapshot]:
        """Drain and acknowledge all pending messages for a member."""
        inbox = self._inboxes.get(target_id)
        if not inbox:
            return []

        messages: list[TeamMessageSnapshot] = []
        while inbox:
            msg = inbox.popleft()
            delivered_msg = TeamMessageSnapshot(
                id=msg.id,
                team_id=msg.team_id,
                sender_id=msg.sender_id,
                sender_name=msg.sender_name,
                target_id=msg.target_id,
                target_name=msg.target_name,
                content=msg.content,
                mode=msg.mode,
                created_at=msg.created_at,
                delivered=True,
            )
            messages.append(delivered_msg)
            self._append_log({"event": "delivered", "message_id": msg.id, "target_id": target_id})

        return messages

    def get_pending_count(self, target_id: str) -> int:
        return len(self._inboxes.get(target_id, ()))

    def list_history(self, limit: int = 100) -> list[dict[str, object]]:
        """List historical raw log records."""
        if self._log_path is None or not self._log_path.is_file():
            return []
        records: list[dict[str, object]] = []
        try:
            for line in self._log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                records.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read mailbox log: %s", exc)
        return records[-limit:]

    # -------------------------------------------------------------------------
    # Cold Recovery & Log Persistence
    # -------------------------------------------------------------------------

    def recover_from_disk(self) -> None:
        """Replay queued-minus-delivered log to restore unconsumed messages."""
        if self._log_path is None or not self._log_path.is_file():
            return

        queued_map: dict[str, TeamMessageSnapshot] = {}
        delivered_set: set[str] = set()
        max_idx = 0

        try:
            for line in self._log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                event = record.get("event")
                if event == "queued":
                    data = record.get("message", {})
                    msg = TeamMessageSnapshot(
                        id=str(data.get("id")),
                        team_id=str(data.get("team_id")),
                        sender_id=str(data.get("sender_id")),
                        sender_name=str(data.get("sender_name")),
                        target_id=str(data.get("target_id")),
                        target_name=str(data.get("target_name")),
                        content=str(data.get("content")),
                        mode=DeliveryMode(str(data.get("mode", "quiet"))),
                        created_at=float(data.get("created_at", time.time())),
                        delivered=False,
                    )
                    queued_map[msg.id] = msg
                    # Track max numeric id
                    try:
                        idx = int(msg.id.rsplit("-", 1)[-1])
                        if idx > max_idx:
                            max_idx = idx
                    except ValueError:
                        pass
                elif event == "delivered":
                    msg_id = str(record.get("message_id", ""))
                    if msg_id:
                        delivered_set.add(msg_id)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cold recovery failed to parse mailbox log: %s", exc)
            return

        self._counter = max_idx
        # Restore pending: queued - delivered
        self._inboxes.clear()
        for msg_id, snapshot in queued_map.items():
            if msg_id not in delivered_set:
                inbox = self._inboxes.setdefault(snapshot.target_id, deque())
                inbox.append(snapshot)

        logger.info(
            "Mailbox cold recovery completed for team %s: %d pending messages restored",
            self.team_id,
            sum(len(q) for q in self._inboxes.values()),
        )

    def _append_log(self, record: dict[str, object]) -> None:
        if self._log_path is None:
            return
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim_log_if_needed()
        except OSError as exc:
            logger.warning("Failed to append to mailbox log: %s", exc)

    def _trim_log_if_needed(self) -> None:
        if self._log_path is None or not self._log_path.is_file():
            return
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= _MAX_JSONL_RECORDS:
                return
            tail = lines[-_MAX_JSONL_RECORDS:]
            atomic_write(self._log_path, "\n".join(tail) + "\n")
        except OSError as exc:
            logger.warning("Failed to trim mailbox log: %s", exc)
