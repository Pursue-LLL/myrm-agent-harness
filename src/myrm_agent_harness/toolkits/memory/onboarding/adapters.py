"""Source adapter implementations for external agent conversation log ingestion.

[INPUT]
- abc: ABC, abstractmethod
- pathlib: Path
- json: loads
- .models: SampledTurnMessage

[OUTPUT]
- BaseAgentSourceAdapter: Protocol and base class for agent log adapters.
- CursorSourceAdapter: Adapter for Cursor logs and session histories.
- ClaudeCodeSourceAdapter: Adapter for Claude Code session transcript files.
- CodexSourceAdapter: Adapter for Codex session files.
- HermesSourceAdapter: Adapter for Hermes Agent history files.
- OpenClawSourceAdapter: Adapter for OpenClaw state session files.

[POS]
Harness framework extensible adapter layer for multi-source agent log extraction.
Adheres to the Open-Closed Principle for adding new agent sources seamlessly.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .models import SampledTurnMessage


class BaseAgentSourceAdapter(ABC):
    """Abstract base adapter defining methods for agent source detection and session extraction."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier of the agent source."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name of the agent source."""

    @abstractmethod
    def detect_active(self) -> bool:
        """Check whether the agent source is present and active on the host machine."""

    @abstractmethod
    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        """Scan and return the most recently modified session files up to limit."""

    @abstractmethod
    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        """Extract turn messages from a single session file with robust fault tolerance."""


class CursorSourceAdapter(BaseAgentSourceAdapter):
    """Adapter for extracting conversations from Cursor workspace and state directories."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".cursor" / "chats")

    @property
    def source_id(self) -> str:
        return "cursor"

    @property
    def display_name(self) -> str:
        return "Cursor IDE"

    def detect_active(self) -> bool:
        return self._base_dir.is_dir()

    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        if not self.detect_active():
            return []
        files = [p for p in self._base_dir.glob("*.json") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        messages: list[SampledTurnMessage] = []
        try:
            content = session_path.read_text(encoding="utf-8")
            data = json.loads(content)
            items = data if isinstance(data, list) else data.get("messages", [])
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                role_val = item.get("role", "user")
                role_str = role_val if role_val in ("user", "assistant", "tool", "system") else "user"
                text = str(item.get("text") or item.get("content") or "")
                created_at = str(item.get("timestamp") or item.get("createdAt") or "")
                messages.append(
                    SampledTurnMessage(
                        source_id=self.source_id,
                        conversation_id=session_path.stem,
                        message_id=f"{session_path.stem}-{idx}",
                        role=role_str,
                        text=text,
                        created_at=created_at,
                    )
                )
        except Exception:
            return []
        return messages


class ClaudeCodeSourceAdapter(BaseAgentSourceAdapter):
    """Adapter for Claude Code CLI session transcripts."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".claude" / "projects")

    @property
    def source_id(self) -> str:
        return "claude_code"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    def detect_active(self) -> bool:
        return self._base_dir.is_dir()

    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        if not self.detect_active():
            return []
        files = [p for p in self._base_dir.glob("**/*.jsonl") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        messages: list[SampledTurnMessage] = []
        try:
            with session_path.open("r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        if not isinstance(record, dict):
                            continue
                        role_val = record.get("role", "user")
                        role_str = role_val if role_val in ("user", "assistant", "tool", "system") else "user"
                        text = str(record.get("text") or record.get("message") or "")
                        created_at = str(record.get("created_at") or "")
                        messages.append(
                            SampledTurnMessage(
                                source_id=self.source_id,
                                conversation_id=session_path.stem,
                                message_id=f"{session_path.stem}-{idx}",
                                role=role_str,
                                text=text,
                                created_at=created_at,
                            )
                        )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return messages


class CodexSourceAdapter(BaseAgentSourceAdapter):
    """Adapter for OpenAI Codex CLI sessions."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".codex" / "sessions")

    @property
    def source_id(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "Codex"

    def detect_active(self) -> bool:
        return self._base_dir.is_dir()

    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        if not self.detect_active():
            return []
        files = [p for p in self._base_dir.glob("*.jsonl") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        messages: list[SampledTurnMessage] = []
        try:
            with session_path.open("r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        if not isinstance(record, dict):
                            continue
                        role_val = record.get("role", "user")
                        role_str = role_val if role_val in ("user", "assistant", "tool", "system") else "user"
                        text = str(record.get("content") or record.get("text") or "")
                        created_at = str(record.get("timestamp") or "")
                        messages.append(
                            SampledTurnMessage(
                                source_id=self.source_id,
                                conversation_id=session_path.stem,
                                message_id=f"{session_path.stem}-{idx}",
                                role=role_str,
                                text=text,
                                created_at=created_at,
                            )
                        )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return messages


class HermesSourceAdapter(BaseAgentSourceAdapter):
    """Adapter for Hermes Agent local session history."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".hermes" / "history")

    @property
    def source_id(self) -> str:
        return "hermes"

    @property
    def display_name(self) -> str:
        return "Hermes Agent"

    def detect_active(self) -> bool:
        return self._base_dir.is_dir()

    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        if not self.detect_active():
            return []
        files = [p for p in self._base_dir.glob("*.json") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        messages: list[SampledTurnMessage] = []
        try:
            content = session_path.read_text(encoding="utf-8")
            data = json.loads(content)
            items = data if isinstance(data, list) else data.get("messages", [])
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                role_val = item.get("role", "user")
                role_str = role_val if role_val in ("user", "assistant", "tool", "system") else "user"
                text = str(item.get("content") or item.get("text") or "")
                created_at = str(item.get("timestamp") or "")
                messages.append(
                    SampledTurnMessage(
                        source_id=self.source_id,
                        conversation_id=session_path.stem,
                        message_id=f"{session_path.stem}-{idx}",
                        role=role_str,
                        text=text,
                        created_at=created_at,
                    )
                )
        except Exception:
            return []
        return messages


class OpenClawSourceAdapter(BaseAgentSourceAdapter):
    """Adapter for OpenClaw state sessions."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".openclaw" / "state" / "sessions")

    @property
    def source_id(self) -> str:
        return "openclaw"

    @property
    def display_name(self) -> str:
        return "OpenClaw"

    def detect_active(self) -> bool:
        return self._base_dir.is_dir()

    def scan_recent_sessions(self, limit: int = 6) -> list[Path]:
        if not self.detect_active():
            return []
        files = [p for p in self._base_dir.glob("*.jsonl") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]

    def extract_turn_messages(self, session_path: Path) -> list[SampledTurnMessage]:
        messages: list[SampledTurnMessage] = []
        try:
            with session_path.open("r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        if not isinstance(record, dict):
                            continue
                        role_val = record.get("role", "user")
                        role_str = role_val if role_val in ("user", "assistant", "tool", "system") else "user"
                        text = str(record.get("text") or record.get("content") or "")
                        created_at = str(record.get("created_at") or "")
                        messages.append(
                            SampledTurnMessage(
                                source_id=self.source_id,
                                conversation_id=session_path.stem,
                                message_id=f"{session_path.stem}-{idx}",
                                role=role_str,
                                text=text,
                                created_at=created_at,
                            )
                        )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return messages
