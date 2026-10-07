"""[POS]: src/myrm_agent_harness/toolkits/memory/ingestion_gateway/distiller.py
[INPUT]: Normalized VoiceTranscriptSegment sequences from universal parser.
[OUTPUT]: VoiceContextDistiller extracting merged speaker turns, summaries, action items, and decisions.
"""

import re

from .models import VoiceTranscriptSegment


class VoiceContextDistiller:
    """Distiller that merges adjacent speaker utterances and extracts decisions/actions."""

    _ACTION_KEYWORDS = (
        "action item",
        "todo",
        "to-do",
        "will do",
        "assign to",
        "assigned to",
        "deadline",
        "follow up",
        "待办",
        "负责",
        "需要完成",
        "下周完成",
        "截止日期",
        "行动项",
        "跟进",
    )

    _DECISION_KEYWORDS = (
        "decided",
        "we agreed",
        "agreed to",
        "consensus",
        "conclusion",
        "approved",
        "定下来",
        "决定",
        "达成一致",
        "确定",
        "结论是",
        "方案选定",
        "通过了",
    )

    def merge_adjacent_segments(
        self, segments: list[VoiceTranscriptSegment]
    ) -> list[VoiceTranscriptSegment]:
        """Merge consecutive segments from the same speaker."""
        if not segments:
            return []

        merged: list[VoiceTranscriptSegment] = []
        current = segments[0].model_copy()

        for seg in segments[1:]:
            if seg.speaker == current.speaker:
                # Merge into current segment
                current.end_sec = max(current.end_sec, seg.end_sec)
                current.text = f"{current.text} {seg.text}".strip()
                current.confidence = min(current.confidence, seg.confidence)
            else:
                merged.append(current)
                current = seg.model_copy()

        merged.append(current)
        return merged

    def extract_action_items(
        self, segments: list[VoiceTranscriptSegment]
    ) -> list[str]:
        """Extract explicit action items and commitments from transcript."""
        actions: list[str] = []
        seen: set[str] = set()

        for seg in segments:
            text_lower = seg.text.lower()
            if any(kw in text_lower for kw in self._ACTION_KEYWORDS):
                cleaned = re.sub(r"\s+", " ", seg.text).strip()
                entry = f"[{seg.speaker}] {cleaned}"
                if entry not in seen:
                    seen.add(entry)
                    actions.append(entry)
        return actions

    def extract_decisions(
        self, segments: list[VoiceTranscriptSegment]
    ) -> list[str]:
        """Extract confirmed architectural decisions or agreements from transcript."""
        decisions: list[str] = []
        seen: set[str] = set()

        for seg in segments:
            text_lower = seg.text.lower()
            if any(kw in text_lower for kw in self._DECISION_KEYWORDS):
                cleaned = re.sub(r"\s+", " ", seg.text).strip()
                entry = f"[{seg.speaker}] {cleaned}"
                if entry not in seen:
                    seen.add(entry)
                    decisions.append(entry)
        return decisions

    def build_summary(
        self,
        title: str,
        segments: list[VoiceTranscriptSegment],
        distinct_speakers: list[str],
    ) -> str:
        """Construct structured executive summary of the voice recording."""
        if not segments:
            return f"Recording: {title} (No spoken content detected)"

        total_duration = max(0.0, segments[-1].end_sec - segments[0].start_sec)
        minutes = int(total_duration // 60)
        seconds = int(total_duration % 60)
        speaker_str = ", ".join(distinct_speakers) if distinct_speakers else "Unknown"

        header = (
            f"Title: {title} | Duration: {minutes}m {seconds}s | "
            f"Participants: {speaker_str} ({len(distinct_speakers)} total)"
        )

        # Build turn-by-turn narrative excerpt
        key_turns: list[str] = []
        for seg in segments[:10]:  # Highlight first 10 core turns
            snippet = seg.text[:120] + "..." if len(seg.text) > 120 else seg.text
            key_turns.append(f"- {seg.speaker} ({seg.start_sec:.1f}s): {snippet}")

        if len(segments) > 10:
            key_turns.append(f"... (+{len(segments) - 10} more turns)")

        return f"{header}\n" + "\n".join(key_turns)
