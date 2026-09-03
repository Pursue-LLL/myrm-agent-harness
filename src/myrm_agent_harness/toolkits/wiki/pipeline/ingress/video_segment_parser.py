"""Video transcript parsing, sliding-window merging, and markdown synthesis.

[INPUT]
- types.MediaTranscriptSegment (POS: raw subtitle timestamp segment)

[OUTPUT]
- MergedVideoSegment: Aggregated semantic window segment
- format_timestamp / parse_timestamp_str: Time conversions
- adaptive_merge_segments: Sliding window aggregator
- parse_transcript_text_to_segments: Text to structured segments
- build_video_markdown: Markdown formatter with Frontmatter

[POS]
Video transcript parsing and Markdown formatting engine. Normalizes disparate
subtitle sources into timestamp-anchored, readable Markdown sections.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
    MediaTranscriptSegment,
)

_TITLE_CLEAN_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_TIMESTAMP_LINE_RE = re.compile(r"^(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?)\s*(.*)$")


@dataclass(frozen=True, slots=True)
class MergedVideoSegment:
    """Aggregated video transcript segment across a semantic time window."""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


def format_timestamp(seconds: float) -> str:
    """Format total seconds into MM:SS or HH:MM:SS."""
    sec_int = max(0, round(seconds))
    hours = sec_int // 3600
    minutes = (sec_int % 3600) // 60
    rem_secs = sec_int % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{rem_secs:02d}"
    return f"{minutes:02d}:{rem_secs:02d}"


def parse_timestamp_str(time_str: str) -> float:
    """Parse MM:SS or HH:MM:SS string to float seconds."""
    parts = [int(p) for p in time_str.strip().split(":") if p.isdigit()]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 1:
        return float(parts[0])
    return 0.0


def adaptive_merge_segments(
    segments: Sequence[MediaTranscriptSegment],
    *,
    window_duration_seconds: int = 45,
    window_max_chars: int = 350,
) -> list[MergedVideoSegment]:
    """Aggregate fine-grained subtitle lines into coherent semantic paragraphs.

    Prevents fragmenting text into 1-2 second slivers while preserving
    second-level temporal bounding for jumping to video points.
    """
    if not segments:
        return []

    merged: list[MergedVideoSegment] = []
    current_start = segments[0].start_seconds
    current_end = segments[0].end_seconds
    current_texts: list[str] = []
    current_len = 0
    current_speaker = segments[0].speaker

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        speaker_changed = seg.speaker != current_speaker and seg.speaker is not None
        duration_exceeded = (seg.end_seconds - current_start) >= window_duration_seconds
        chars_exceeded = (current_len + len(text)) >= window_max_chars

        if current_texts and (speaker_changed or duration_exceeded or chars_exceeded):
            merged.append(
                MergedVideoSegment(
                    start_seconds=current_start,
                    end_seconds=current_end,
                    text=" ".join(current_texts),
                    speaker=current_speaker,
                )
            )
            current_start = seg.start_seconds
            current_end = seg.end_seconds
            current_texts = [text]
            current_len = len(text)
            current_speaker = seg.speaker
        else:
            current_texts.append(text)
            current_len += len(text)
            current_end = max(current_end, seg.end_seconds)
            if current_speaker is None and seg.speaker:
                current_speaker = seg.speaker

    if current_texts:
        merged.append(
            MergedVideoSegment(
                start_seconds=current_start,
                end_seconds=current_end,
                text=" ".join(current_texts),
                speaker=current_speaker,
            )
        )

    return merged


def parse_transcript_text_to_segments(text: str) -> list[MediaTranscriptSegment]:
    """Convert line-based timestamp text (MM:SS Text) to structured segments."""
    lines = text.strip().splitlines()
    raw_parsed: list[tuple[float, str]] = []

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        match = _TIMESTAMP_LINE_RE.match(cleaned)
        if match:
            t_str, content = match.group(1), match.group(2).strip()
            sec = parse_timestamp_str(t_str)
            raw_parsed.append((sec, content))
        else:
            if raw_parsed:
                prev_sec, prev_text = raw_parsed[-1]
                raw_parsed[-1] = (prev_sec, f"{prev_text} {cleaned}")
            else:
                raw_parsed.append((0.0, cleaned))

    segments: list[MediaTranscriptSegment] = []
    for i, (start_sec, content) in enumerate(raw_parsed):
        if i + 1 < len(raw_parsed):
            end_sec = max(start_sec + 2.0, raw_parsed[i + 1][0])
        else:
            end_sec = start_sec + 5.0
        segments.append(
            MediaTranscriptSegment(
                start_seconds=start_sec,
                end_seconds=end_sec,
                text=content,
            )
        )

    return segments


def slugify_video_title(text: str, fallback_hash: str) -> str:
    """Generate a filesystem-safe slug from a video title."""
    cleaned = _TITLE_CLEAN_RE.sub("", text.lower())
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = f"video_{fallback_hash[:8]}"
    return cleaned[:60]


def build_video_markdown(
    *,
    title: str,
    source_url: str,
    duration_str: str,
    platform: str,
    author: str,
    merged_segments: Sequence[MergedVideoSegment],
    keyframes_map: dict[float, str] | None = None,
) -> str:
    """Generate standardized Markdown with Frontmatter and timestamp sections."""
    lines: list[str] = [
        "---",
        f'title: "{title.replace(chr(34), "")}"',
        f'source_url: "{source_url.replace(chr(34), "")}"',
        'content_type: "video"',
        f'platform: "{platform}"',
        f'duration: "{duration_str}"',
        f'author: "{author.replace(chr(34), "")}"',
        f"clipped_at: {datetime.now(UTC).isoformat()}",
        "---",
        "",
        f"# {title}",
        "",
        f"> **来源平台:** {platform.title()} | **时长:** {duration_str or '未知'} | **作者/UP主:** {author or '未知'}",
        "",
    ]

    kf_map = keyframes_map or {}

    for seg in merged_segments:
        start_fmt = format_timestamp(seg.start_seconds)
        end_fmt = format_timestamp(seg.end_seconds)
        lines.append(f"### [{start_fmt} - {end_fmt}]")
        lines.append("")

        for kf_time, rel_img_path in list(kf_map.items()):
            if seg.start_seconds <= kf_time <= seg.end_seconds:
                lines.append(f"![画面截图 {format_timestamp(kf_time)}]({rel_img_path})")
                lines.append("")

        if seg.speaker:
            lines.append(f"**{seg.speaker}:** {seg.text}")
        else:
            lines.append(seg.text)
        lines.append("")

    return "\n".join(lines).strip() + "\n"
