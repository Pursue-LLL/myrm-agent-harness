"""Core engine for Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).

[INPUT]
- proactive_recall_types: Entities, detection records, configurations, and probe outcomes.

[OUTPUT]
- ContextGapAutoProbeEngine: Ledger maintenance and static context gap reference probe orchestrator.

[POS]
- Proactively identifies references to pruned or compacted historical entities,
- generating deterministic nudge injections to prompt autonomous history tool invocation.
"""

from __future__ import annotations

import re
import time
from typing import Pattern

from myrm_agent_harness.agent.context_management.proactive_recall.proactive_recall_types import (
    ContextGapDetection,
    EntityType,
    PrunedEntityRecord,
    ProactiveRecallNudgeConfig,
    ProactiveRecallProbeResult,
)

# Common regex patterns for entity extraction from pruned context payloads
_RE_FILE_PATH: Pattern[str] = re.compile(r"\b(?:[a-zA-Z0-9_\-\.]+/)+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]{1,6}\b")
_RE_URL: Pattern[str] = re.compile(r"https?://[^\s<>\"']+")
_RE_ERROR_CODE: Pattern[str] = re.compile(r"\b(?:ERR_|ERROR_|STATUS_)[A-Z0-9_]{2,}\b")
_RE_IDENTIFIER: Pattern[str] = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]{3,})`")


class ContextGapAutoProbeEngine:
    """Manages pruned entity footprints and probes active message flow for cognitive recall gaps."""

    def __init__(self, default_config: ProactiveRecallNudgeConfig | None = None) -> None:
        self._default_config = default_config or ProactiveRecallNudgeConfig()
        # session_id -> entity_name.lower() -> PrunedEntityRecord
        self._ledger: dict[str, dict[str, PrunedEntityRecord]] = {}

    def record_pruned_entities(
        self,
        session_id: str,
        turn_index: int,
        pruned_text: str = "",
        custom_entities: list[PrunedEntityRecord] | None = None,
    ) -> list[PrunedEntityRecord]:
        """Extracts and records entity footprints from pruned text or structured inputs."""
        session_records = self._ledger.setdefault(session_id, {})
        new_records: list[PrunedEntityRecord] = []

        # 1. Ingest explicit custom entities
        if custom_entities:
            for entity in custom_entities:
                key = entity.entity_name.lower()
                session_records[key] = entity
                new_records.append(entity)

        # 2. Extract automatic heuristic entities from pruned_text
        if pruned_text:
            extracted = self._extract_heuristic_entities(pruned_text, turn_index)
            for entity in extracted:
                key = entity.entity_name.lower()
                if key not in session_records:
                    session_records[key] = entity
                    new_records.append(entity)

        return new_records

    def get_pruned_entities(self, session_id: str) -> list[PrunedEntityRecord]:
        """Returns all recorded entity footprints for a session."""
        records = self._ledger.get(session_id, {})
        return list(records.values())

    def probe_context_gaps(
        self,
        session_id: str,
        active_messages: list[dict[str, object]],
        current_input: str,
        config: ProactiveRecallNudgeConfig | None = None,
    ) -> ProactiveRecallProbeResult:
        """Inspects current input against pruned footprint ledger to identify active cognitive gaps."""
        start_time = time.perf_counter()
        cfg = config or self._default_config
        session_records = self._ledger.get(session_id, {})

        if not session_records or not current_input.strip():
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ProactiveRecallProbeResult(
                session_id=session_id,
                detected_gaps=[],
                nudge_block=None,
                scanned_entity_count=len(session_records),
                probe_latency_ms=round(latency_ms, 2),
            )

        # Build active context token frequency map to check definition absence
        active_corpus = " ".join(str(m.get("content", "")) for m in active_messages).lower()
        input_lower = current_input.lower()

        detected: list[ContextGapDetection] = []

        for key, record in session_records.items():
            if len(key) < cfg.min_entity_len:
                continue

            # Check if current input explicitly references this pruned entity
            if key in input_lower:
                # If active context does not define or explain the entity (only low occurrences or missing)
                # Count occurrences in active messages
                active_count = active_corpus.count(key)
                if active_count <= 1:
                    snippet = self._extract_snippet(current_input, record.entity_name)
                    detected.append(
                        ContextGapDetection(
                            entity_name=record.entity_name,
                            entity_type=record.entity_type,
                            turn_index=record.turn_index,
                            context_snippet=snippet,
                            confidence=0.95 if active_count == 0 else 0.80,
                        )
                    )

        # Sort by confidence descending, take top max_nudges_per_turn
        detected.sort(key=lambda d: (-d.confidence, -d.turn_index))
        top_gaps = detected[: cfg.max_nudges_per_turn]

        nudge_block = self._render_nudge_block(top_gaps, cfg) if top_gaps else None
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return ProactiveRecallProbeResult(
            session_id=session_id,
            detected_gaps=top_gaps,
            nudge_block=nudge_block,
            scanned_entity_count=len(session_records),
            probe_latency_ms=round(latency_ms, 2),
        )

    def clear_session(self, session_id: str) -> None:
        """Purges entity footprint ledger for a session."""
        self._ledger.pop(session_id, None)

    def _extract_heuristic_entities(
        self, text: str, turn_index: int
    ) -> list[PrunedEntityRecord]:
        """Scans text for common technical entity patterns."""
        records: list[PrunedEntityRecord] = []
        seen: set[str] = set()

        # 1. File paths
        for match in _RE_FILE_PATH.findall(text):
            cleaned_file = match.rstrip(".,;:!?)'\"")
            if cleaned_file not in seen and len(cleaned_file) >= 4:
                seen.add(cleaned_file)
                records.append(
                    PrunedEntityRecord(
                        entity_name=cleaned_file,
                        entity_type=EntityType.FILE_PATH,
                        turn_index=turn_index,
                        summary_hint=f"File path from turn {turn_index}",
                    )
                )

        # 2. URLs
        for match in _RE_URL.findall(text):
            cleaned_url = match.rstrip(".,;:!?)'\"")
            if cleaned_url not in seen:
                seen.add(cleaned_url)
                records.append(
                    PrunedEntityRecord(
                        entity_name=cleaned_url,
                        entity_type=EntityType.URL,
                        turn_index=turn_index,
                        summary_hint=f"URL reference from turn {turn_index}",
                    )
                )

        # 3. Error codes
        for match in _RE_ERROR_CODE.findall(text):
            if match not in seen:
                seen.add(match)
                records.append(
                    PrunedEntityRecord(
                        entity_name=match,
                        entity_type=EntityType.ERROR_CODE,
                        turn_index=turn_index,
                        summary_hint=f"Error code from turn {turn_index}",
                    )
                )

        # 4. Code identifiers in backticks
        for match in _RE_IDENTIFIER.findall(text):
            if match not in seen and len(match) >= 3:
                seen.add(match)
                records.append(
                    PrunedEntityRecord(
                        entity_name=match,
                        entity_type=EntityType.IDENTIFIER,
                        turn_index=turn_index,
                        summary_hint=f"Code identifier from turn {turn_index}",
                    )
                )

        return records

    def _extract_snippet(self, text: str, target: str, window: int = 40) -> str:
        """Extracts context window snippet surrounding the entity match."""
        idx = text.lower().find(target.lower())
        if idx == -1:
            return text[:80]
        start = max(0, idx - window)
        end = min(len(text), idx + len(target) + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    def _render_nudge_block(
        self, gaps: list[ContextGapDetection], cfg: ProactiveRecallNudgeConfig
    ) -> str:
        """Renders proactive recall hint prompt formatted for agent consumption."""
        lines: list[str] = []
        for gap in gaps:
            line = cfg.nudge_template.format(
                name=gap.entity_name,
                entity_type=gap.entity_type.value,
                turn=gap.turn_index,
            )
            lines.append(f"- {line}")

        body = "\n".join(lines)
        if cfg.include_xml_wrapper:
            return f"<context-gap-nudge>\n{body}\n</context-gap-nudge>"
        return body
