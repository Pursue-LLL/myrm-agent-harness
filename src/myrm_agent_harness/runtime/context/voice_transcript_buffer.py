"""Voice transcript buffer and conversation flow state tracker.

Buffers spoken dialogue turns in real-time, captures barge-in interruptions,
tracks consultation phases, and detects user alignment and approval signals.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from .voice_spec_extractor_types import (
    VoiceConsultantPhase,
    VoiceTranscriptTurn,
)

ALIGNMENT_SIGNAL_PHRASES: frozenset[str] = frozenset(
    {
        "就按这个方案做吧",
        "按这个方案做吧",
        "赞同，开始执行",
        "同意，开始执行",
        "方案定下了",
        "按你说的来",
        "开始做吧",
        "好的，就这么办",
        "就这么做",
        "lgtm",
        "let's proceed",
        "approved",
        "sounds good, let's do it",
        "sounds great, let's build this",
    }
)


class VoiceTranscriptBuffer:
    """Manages full-duplex voice consultation transcripts and phase transitions."""

    def __init__(self) -> None:
        self._turns: list[VoiceTranscriptTurn] = []
        self._counter: int = 0
        self._phase: VoiceConsultantPhase = VoiceConsultantPhase.EXPLORATION

    def record_turn(
        self,
        speaker: str,
        text: str,
        is_interruption: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> VoiceTranscriptTurn:
        """Record an individual spoken turn into the buffer."""
        cleaned_text = text.strip()
        self._counter += 1
        turn_id = f"vturn_{self._counter}_{uuid.uuid4().hex[:6]}"
        turn = VoiceTranscriptTurn(
            turn_id=turn_id,
            speaker=speaker.lower(),
            transcript_text=cleaned_text,
            timestamp_ms=int(time.time() * 1000),
            is_interruption=is_interruption,
            metadata=dict(metadata or {}),
        )
        self._turns.append(turn)

        # Update consultant phase dynamically
        if self.detect_alignment_signal():
            self._phase = VoiceConsultantPhase.FINAL_ALIGNMENT
        elif len(self._turns) < 3:
            self._phase = VoiceConsultantPhase.EXPLORATION
        elif len(self._turns) < 6:
            self._phase = VoiceConsultantPhase.DEEP_DIVE
        else:
            self._phase = VoiceConsultantPhase.TRADE_OFF_ANALYSIS

        return turn

    def detect_alignment_signal(self) -> bool:
        """Evaluate if the latest user turn signaled final consensus to build."""
        for turn in reversed(self._turns):
            if turn.speaker == "user":
                normalized = turn.transcript_text.lower().strip()
                for phrase in ALIGNMENT_SIGNAL_PHRASES:
                    if phrase in normalized:
                        return True
                break
        return False

    @property
    def current_phase(self) -> VoiceConsultantPhase:
        """Return the current phase of the voice consultation."""
        return self._phase

    def set_phase(self, phase: VoiceConsultantPhase) -> None:
        """Explicitly override the consultant phase."""
        self._phase = phase

    def get_turns(self) -> list[VoiceTranscriptTurn]:
        """Return all recorded turns in chronological order."""
        return list(self._turns)

    def turn_count(self) -> int:
        """Return total number of recorded turns."""
        return len(self._turns)

    def export_raw_transcript(self) -> str:
        """Format the dialogue buffer into a human-readable transcript."""
        lines: list[str] = []
        for t in self._turns:
            prefix = f"[{t.speaker.upper()}]"
            if t.is_interruption:
                prefix += " (INTERRUPTION)"
            lines.append(f"{prefix}: {t.transcript_text}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Reset the transcript buffer and consultant state."""
        self._turns.clear()
        self._counter = 0
        self._phase = VoiceConsultantPhase.EXPLORATION
