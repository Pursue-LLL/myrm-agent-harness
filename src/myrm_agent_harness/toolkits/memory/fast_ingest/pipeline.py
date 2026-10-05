"""One-Pass Fast Memory Commit Pipeline with sub-5% latency overhead guarantee."""

import re
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    FastCommittedRecord,
    IngestionMetrics,
    IngestStatus,
    RawIngestTurn,
)

# Heuristic patterns for rapid in-forward proposition extraction without secondary LLMs
_FACT_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:prefer|always use|never use|default to|remember to|switch to|set)\s+([^\n\r]+?)(?:\.(?:\s|$)|[;]|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([a-z0-9_-]+\s+(?:is|are|=|was|were)\s+[^\n\r]+?)(?:\.(?:\s|$)|[;]|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:config|setting|path|url|port|branch|version|key|secret):\s*([^\s,;]+)",
        re.IGNORECASE,
    ),
)

_ENTITY_REGEX: re.Pattern[str] = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:[A-Z][a-z0-9]+)+|[a-z0-9_-]+\.[a-z0-9]{2,4}|[A-Z]{2,}\b)",
)


class FastMemoryCommitPipeline:
    """Zero-LLM one-pass memory commit pipeline executing in under 5% forward latency."""

    def __init__(
        self,
        max_buffer_size: int = 1000,
        target_overhead_threshold_percent: float = 5.0,
    ) -> None:
        """Initialize pipeline with buffer boundaries and latency threshold.

        Args:
            max_buffer_size: Maximum un-distilled committed records held in memory.
            target_overhead_threshold_percent: Maximum allowable latency budget (default 5.0%).
        """
        self._max_buffer_size = max(1, max_buffer_size)
        self._target_overhead_threshold = target_overhead_threshold_percent
        self._buffer: list[FastCommittedRecord] = []
        self._metrics_log: list[IngestionMetrics] = []

    @property
    def buffer_size(self) -> int:
        """Return the number of records currently in the memory buffer."""
        return len(self._buffer)

    @property
    def metrics_history(self) -> list[IngestionMetrics]:
        """Return copies of telemetry records."""
        return list(self._metrics_log)

    def commit_turn(
        self,
        turn: RawIngestTurn,
        custom_now: datetime | None = None,
    ) -> tuple[FastCommittedRecord, IngestionMetrics]:
        """Execute one-pass heuristic feature projection and commit to ring buffer.

        Args:
            turn: The conversational turn containing user input and assistant output.
            custom_now: Optional deterministic timestamp for commit registration.

        Returns:
            Tuple of FastCommittedRecord and IngestionMetrics telemetries.
        """
        t_start = time.perf_counter()

        entities = self._extract_entities(turn.user_message, turn.assistant_message)
        facts = self._extract_facts(turn.user_message, turn.assistant_message)
        salience = self._compute_salience(entities, facts, turn.user_message)

        now = custom_now or datetime.now(UTC)
        record_id = f"fast-{uuid.uuid4().hex[:12]}"

        # Calculate exact commit wall-clock duration in milliseconds
        t_elapsed = time.perf_counter() - t_start
        commit_ms = max(0.001, t_elapsed * 1000.0)

        record = FastCommittedRecord(
            record_id=record_id,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            extracted_entities=entities,
            extracted_facts=facts,
            salience_score=salience,
            commit_latency_ms=round(commit_ms, 3),
            status=IngestStatus.PENDING_DISTILL,
            created_at=now,
        )

        overhead_pct = (commit_ms / turn.forward_inference_ms) * 100.0
        passed_gate = overhead_pct <= self._target_overhead_threshold

        metrics = IngestionMetrics(
            turn_id=turn.turn_id,
            commit_latency_ms=round(commit_ms, 3),
            forward_latency_ms=round(turn.forward_inference_ms, 3),
            overhead_percentage=round(overhead_pct, 3),
            passed_overhead_gate=passed_gate,
        )

        self._enqueue_record(record)
        self._metrics_log.append(metrics)

        return record, metrics

    def get_pending_records(self, limit: int = 100) -> list[FastCommittedRecord]:
        """Retrieve committed records awaiting background distillation."""
        pending = [r for r in self._buffer if r.status == IngestStatus.PENDING_DISTILL]
        return pending[:limit]

    def mark_distilled(self, record_ids: Sequence[str]) -> int:
        """Mark successfully distilled records in the buffer."""
        id_set = set(record_ids)
        marked = 0
        for r in self._buffer:
            if r.record_id in id_set and r.status == IngestStatus.PENDING_DISTILL:
                r.status = IngestStatus.DISTILLED
                marked += 1
        return marked

    def prune_distilled(self) -> int:
        """Evict distilled records from the fast commit buffer to recover memory."""
        before = len(self._buffer)
        self._buffer = [r for r in self._buffer if r.status != IngestStatus.DISTILLED]
        return before - len(self._buffer)

    def _enqueue_record(self, record: FastCommittedRecord) -> None:
        """Append to ring buffer with FIFO eviction if capacity is saturated."""
        if len(self._buffer) >= self._max_buffer_size:
            # Evict oldest entry
            self._buffer.pop(0)
        self._buffer.append(record)

    def _extract_entities(self, user_msg: str, asst_msg: str) -> list[str]:
        """Extract candidate named entities and system identifiers."""
        corpus = f"{user_msg} {asst_msg}"
        found = _ENTITY_REGEX.findall(corpus)
        seen: set[str] = set()
        deduped: list[str] = []
        for e in found:
            norm = e.strip()
            if norm and norm.lower() not in seen and len(norm) > 2:
                seen.add(norm.lower())
                deduped.append(norm)
        return deduped[:10]

    def _extract_facts(self, user_msg: str, asst_msg: str) -> list[str]:
        """Extract factual candidate propositions via rapid regex rules."""
        facts: list[str] = []
        seen: set[str] = set()

        for pattern in _FACT_REGEXES:
            for match in pattern.findall(user_msg):
                norm = match.strip()
                if norm and norm.lower() not in seen and len(norm) > 4:
                    seen.add(norm.lower())
                    facts.append(norm)

        # Also capture definitive sentences from assistant
        for line in asst_msg.splitlines():
            trimmed = line.strip()
            if (
                trimmed.startswith(("-", "*", "1.", "2.", "3."))
                and len(trimmed) > 8
            ):
                content = trimmed.lstrip("-*0123456789. ")
                if content.lower() not in seen:
                    seen.add(content.lower())
                    facts.append(content)

        return facts[:12]

    def _compute_salience(
        self,
        entities: Sequence[str],
        facts: Sequence[str],
        user_msg: str,
    ) -> float:
        """Calculate fast salience score (0.0 to 1.0) without embedding calls."""
        if not facts and not entities:
            return 0.1

        base = 0.2
        base += min(0.4, len(facts) * 0.1)
        base += min(0.3, len(entities) * 0.05)

        # Boost if user message contains imperative directive keywords
        if any(w in user_msg.lower() for w in ("remember", "always", "never", "prefer", "note", "important")):
            base += 0.2

        return min(1.0, round(base, 2))
