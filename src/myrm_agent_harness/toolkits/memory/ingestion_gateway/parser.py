"""[POS]: src/myrm_agent_harness/toolkits/memory/ingestion_gateway/parser.py
[INPUT]: Raw transcripts in Plaud JSON, WebVTT, SRT, or raw multi-speaker text formats.
[OUTPUT]: TranscriptUniversalParser producing normalized VoiceTranscriptSegment sequences.
"""

import json
import re

from .models import ContextIngestionPayload, IngestionSourceType, VoiceTranscriptSegment


class TranscriptUniversalParser:
    """Universal parser for multi-modal audio transcripts and hardware recorder payloads."""

    def parse(self, payload: ContextIngestionPayload) -> list[VoiceTranscriptSegment]:
        """Dispatch to format-specific parser based on source type or payload heuristic."""
        content = payload.raw_payload.strip()
        if not content:
            return []

        if payload.source_type == IngestionSourceType.PLAUD_VOICE_CARD or content.startswith("{"):
            try:
                return self.parse_plaud_json(content)
            except Exception:
                pass

        if payload.source_type == IngestionSourceType.WEBVTT or content.startswith("WEBVTT"):
            return self.parse_webvtt(content)

        if payload.source_type == IngestionSourceType.SRT or re.search(r"^\d+\s*\n\d{2}:\d{2}:\d{2}", content):
            return self.parse_srt(content)

        return self.parse_raw_text(content)

    def parse_plaud_json(self, json_str: str) -> list[VoiceTranscriptSegment]:
        """Parse Plaud voice recorder export JSON or standard Whisper transcript dict."""
        data = json.loads(json_str)
        segments: list[VoiceTranscriptSegment] = []

        # Support both 'transcription' array or 'segments' array
        raw_items = data.get("transcription") or data.get("segments") or data.get("items")
        if not isinstance(raw_items, list):
            # Fallback to single text
            text = str(data.get("text", "")).strip()
            if text:
                segments.append(VoiceTranscriptSegment(speaker="Speaker", start_sec=0.0, end_sec=0.0, text=text))
            return segments

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            spk = str(item.get("speaker") or item.get("speaker_name") or "Speaker")
            text = str(item.get("content") or item.get("text") or "").strip()
            if not text:
                continue

            start_t = float(item.get("start_time") or item.get("start") or 0.0)
            end_t = float(item.get("end_time") or item.get("end") or start_t)
            conf = float(item.get("confidence") or 1.0)

            segments.append(
                VoiceTranscriptSegment(
                    speaker=spk,
                    start_sec=max(0.0, start_t),
                    end_sec=max(start_t, end_t),
                    text=text,
                    confidence=min(1.0, max(0.0, conf)),
                )
            )
        return segments

    def parse_webvtt(self, vtt_str: str) -> list[VoiceTranscriptSegment]:
        """Parse standard WebVTT cues into normalized segments."""
        segments: list[VoiceTranscriptSegment] = []
        # Pattern: 00:01.000 --> 00:04.000 or 00:00:01.000 --> 00:00:04.000
        cue_pattern = re.compile(
            r"((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}\.\d{3})[^\n]*\n(.*?)(?=\n\n|\Z)",
            re.DOTALL,
        )

        for match in cue_pattern.finditer(vtt_str):
            start_str, end_str, body = match.groups()
            body_clean = body.strip()
            if not body_clean:
                continue

            # Detect voice tag <v Speaker Name>
            speaker = "Speaker"
            v_match = re.match(r"<v\s+([^>]+)>(.*)", body_clean, re.DOTALL)
            if v_match:
                speaker = v_match.group(1).strip()
                body_clean = re.sub(r"</v>", "", v_match.group(2)).strip()

            start_sec = self._parse_timestamp(start_str)
            end_sec = self._parse_timestamp(end_str)
            segments.append(
                VoiceTranscriptSegment(
                    speaker=speaker,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    text=body_clean,
                )
            )
        return segments

    def parse_srt(self, srt_str: str) -> list[VoiceTranscriptSegment]:
        """Parse standard SubRip SRT subtitles into normalized segments."""
        segments: list[VoiceTranscriptSegment] = []
        blocks = re.split(r"\n\s*\n", srt_str.strip())

        time_pattern = re.compile(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
        )

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue

            # Second line usually contains timestamp
            match = time_pattern.search(lines[1]) if len(lines) >= 2 else None
            text_lines = lines[2:]
            if not match and len(lines) >= 1:
                match = time_pattern.search(lines[0])
                text_lines = lines[1:]

            if not match:
                continue

            start_sec = self._parse_timestamp(match.group(1).replace(",", "."))
            end_sec = self._parse_timestamp(match.group(2).replace(",", "."))
            text = " ".join(text_lines)

            # Check if speaker is indicated like "Alice: hello"
            speaker = "Speaker"
            spk_match = re.match(r"^([^:：]{2,20})[:：]\s*(.*)$", text)
            if spk_match:
                speaker = spk_match.group(1).strip()
                text = spk_match.group(2).strip()

            if text:
                segments.append(
                    VoiceTranscriptSegment(
                        speaker=speaker,
                        start_sec=start_sec,
                        end_sec=end_sec,
                        text=text,
                    )
                )
        return segments

    def parse_raw_text(self, text: str) -> list[VoiceTranscriptSegment]:
        """Parse raw multi-line transcript with optional 'Speaker:' markers."""
        segments: list[VoiceTranscriptSegment] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        current_speaker = "Speaker"
        sec_counter = 0.0

        for line in lines:
            spk_match = re.match(r"^([^:：]{2,20})[:：]\s*(.*)$", line)
            if spk_match:
                current_speaker = spk_match.group(1).strip()
                line_text = spk_match.group(2).strip()
            else:
                line_text = line

            if line_text:
                segments.append(
                    VoiceTranscriptSegment(
                        speaker=current_speaker,
                        start_sec=sec_counter,
                        end_sec=sec_counter + 5.0,
                        text=line_text,
                    )
                )
                sec_counter += 5.0
        return segments

    @staticmethod
    def _parse_timestamp(ts: str) -> float:
        parts = ts.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600.0 + float(m) * 60.0 + float(s)
        if len(parts) == 2:
            m, s = parts
            return float(m) * 60.0 + float(s)
        return 0.0
