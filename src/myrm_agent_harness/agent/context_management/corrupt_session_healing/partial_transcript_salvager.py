"""Partial transcript salvager for recovering valid conversation history from corrupt files.

[INPUT]
- healing_types: SalvagedMessageItem, HealingSuiteConfig.

[OUTPUT]
- PartialTranscriptSalvager: Extracts valid individual message entries from
  truncated or syntactically broken JSON/JSONL transcript payloads.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: partial_transcript_salvager.py
"""

import json
import re
from typing import List, Optional, Sequence
from myrm_agent_harness.agent.context_management.corrupt_session_healing.healing_types import (
    HealingSuiteConfig,
    SalvagedMessageItem,
)


class PartialTranscriptSalvager:
    """Attempts best-effort salvage of uncorrupted messages from damaged transcripts."""

    _JSON_OBJECT_REGEX = re.compile(r"(\{[^{}]*\"role\"\s*:\s*\"[^\"]+\"[^{}]*\})")

    def __init__(self, config: Optional[HealingSuiteConfig] = None) -> None:
        self._config = config or HealingSuiteConfig()

    def salvage(self, raw_payload: str) -> Sequence[SalvagedMessageItem]:
        """Recovers well-formed message records from damaged payload strings.

        Args:
            raw_payload: Raw string content from corrupted storage.

        Returns:
            A sequence of successfully salvaged messages.
        """
        if not raw_payload or not raw_payload.strip():
            return tuple()

        # 1. First attempt: standard JSON array parsing
        clean_result = self._try_parse_full_json(raw_payload)
        if clean_result is not None:
            return clean_result

        # 2. Second attempt: line-by-line JSONL recovery
        jsonl_result = self._try_parse_jsonl(raw_payload)
        if jsonl_result:
            return jsonl_result

        # 3. Third attempt: regex-based individual JSON message block recovery
        return self._salvage_via_regex(raw_payload)

    def _try_parse_full_json(self, raw: str) -> Optional[Sequence[SalvagedMessageItem]]:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                items: List[SalvagedMessageItem] = []
                for idx, entry in enumerate(data):
                    if isinstance(entry, dict) and "role" in entry and "content" in entry:
                        msg_id = str(entry.get("message_id", f"salvaged-{idx}"))
                        role = str(entry.get("role", "user"))
                        content = str(entry.get("content", ""))
                        items.append(
                            SalvagedMessageItem(
                                message_id=msg_id,
                                role=role,
                                content=content,
                                salvaged_index=idx,
                            )
                        )
                return tuple(items[: self._config.max_salvaged_messages])
        except Exception:
            pass
        return None

    def _try_parse_jsonl(self, raw: str) -> Sequence[SalvagedMessageItem]:
        items: List[SalvagedMessageItem] = []
        lines = raw.splitlines()
        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                entry = json.loads(line_str)
                if isinstance(entry, dict) and "role" in entry and "content" in entry:
                    msg_id = str(entry.get("message_id", f"salvaged-line-{idx}"))
                    items.append(
                        SalvagedMessageItem(
                            message_id=msg_id,
                            role=str(entry.get("role", "user")),
                            content=str(entry.get("content", "")),
                            salvaged_index=len(items),
                        )
                    )
            except Exception:
                continue
        return tuple(items[: self._config.max_salvaged_messages])

    def _salvage_via_regex(self, raw: str) -> Sequence[SalvagedMessageItem]:
        items: List[SalvagedMessageItem] = []
        matches = self._JSON_OBJECT_REGEX.findall(raw)
        for idx, match_text in enumerate(matches):
            try:
                entry = json.loads(match_text)
                if isinstance(entry, dict) and "role" in entry:
                    msg_id = str(entry.get("message_id", f"salvaged-rx-{idx}"))
                    items.append(
                        SalvagedMessageItem(
                            message_id=msg_id,
                            role=str(entry.get("role", "user")),
                            content=str(entry.get("content", "")),
                            salvaged_index=len(items),
                        )
                    )
            except Exception:
                continue
        return tuple(items[: self._config.max_salvaged_messages])
