"""Core audio fact distillation worker for LTRA cognitive pipeline.

[POS]
随身感知事实蒸馏核心执行器。对多说话人带时间戳录音切片进行客套噪音过滤、
语义关系提取，提炼出[主体][诉求][承诺][卡点]四元组事实，并构建毫秒级原声防篡改锚点。

[INPUT]
- DiarizedTranscriptSegment 序列
- 可选说话人别名与项目/智能体上下文

[OUTPUT]
- AudioFactDistillationWorker: 结构化事实四元组蒸馏器
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .guard import SensitiveAudioFactGuard
from .identity_resolver import SpeakerIdentityResolver
from .models import (
    AudioTimestampAnchor,
    CognitiveFactQuadruple,
    DiarizedTranscriptSegment,
)


class AudioFactDistillationWorker:
    """Distills structured cognitive fact quadruples from diarized conversation turns."""

    # Heuristic markers for core business demands
    _DEMAND_PATTERNS = (
        re.compile(r"(?:需要|要求|必须|希望|诉求是|核心关注|务必做到|要实现)\s*([^，。！？；;\n]+)", re.IGNORECASE),
        re.compile(r"(?:need|require|demand|must have|request)\s+([^.,!?;\n]+)", re.IGNORECASE),
    )

    # Heuristic markers for explicit verbal commitments
    _COMMITMENT_PATTERNS = (
        re.compile(r"(?:我们保证|承诺|答应|同意|可以做到|没问题|会在\w+交付|支持这个)\s*([^，。！？；;\n]*)", re.IGNORECASE),
        re.compile(r"(?:we promise|agreed|commit to|will deliver|guarantee)\s+([^.,!?;\n]*)", re.IGNORECASE),
    )

    # Heuristic markers for pending issues, concerns, or blockers
    _BLOCKER_PATTERNS = (
        re.compile(r"(?:卡点|风险|担心|难点|待确认|待商榷|待评估|阻碍在于)\s*([^，。！？；;\n]+)", re.IGNORECASE),
        re.compile(r"(?:blocker|risk|concern|pending|uncertain about)\s+([^.,!?;\n]+)", re.IGNORECASE),
    )

    def __init__(
        self,
        identity_resolver: SpeakerIdentityResolver | None = None,
        min_confidence: float = 0.4,
        min_text_len: int = 3,
    ) -> None:
        """Initialize distillation worker."""
        self._resolver = identity_resolver or SpeakerIdentityResolver()
        self._min_confidence = min_confidence
        self._min_text_len = min_text_len

    def distill_facts(
        self,
        segments: Sequence[DiarizedTranscriptSegment],
        audio_id: str = "voice_session_rec",
        project_id: str | None = None,
        target_agent_id: str | None = None,
    ) -> list[CognitiveFactQuadruple]:
        """Process diarized turns into structured cognitive fact quadruples."""
        distilled: list[CognitiveFactQuadruple] = []

        # Filter low confidence & trivial chatter
        valid_segments = [
            s for s in segments
            if s.confidence >= self._min_confidence and len(s.text.strip()) >= self._min_text_len
        ]

        if not valid_segments:
            return distilled

        for segment in valid_segments:
            resolved_subject = self._resolver.resolve(segment.speaker_id, segment.text)

            demand_desc = self._extract_first_match(segment.text, self._DEMAND_PATTERNS)
            commitment_desc = self._extract_first_match(segment.text, self._COMMITMENT_PATTERNS)
            blocker_desc = self._extract_first_match(segment.text, self._BLOCKER_PATTERNS)

            # If segment contains at least one actionable cognitive dimension
            if demand_desc or commitment_desc or blocker_desc:
                # Primary demand fallback if only commitment or blocker mentioned
                effective_demand = demand_desc or (
                    f"围绕 '{segment.text[:35]}' 的相关技术/业务诉求"
                )
                effective_commitment = commitment_desc or "待跟进明确"
                effective_blocker = blocker_desc or "暂无明确卡点"

                # Check commercial confidentiality
                is_confidential, _ = SensitiveAudioFactGuard.evaluate_confidentiality(segment.text)

                anchor = AudioTimestampAnchor.create(
                    audio_id=audio_id,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    verbatim_quote=segment.text.strip(),
                )

                fact = CognitiveFactQuadruple.create(
                    subject=resolved_subject,
                    demand=effective_demand,
                    commitment=effective_commitment,
                    pending_issue=effective_blocker,
                    anchors=[anchor],
                    project_id=project_id,
                    target_agent_id=target_agent_id,
                    is_confidential=is_confidential,
                )
                distilled.append(fact)

        return distilled

    def _extract_first_match(
        self,
        text: str,
        patterns: tuple[re.Pattern[str], ...],
    ) -> str | None:
        """Extract first meaningful match substring from text."""
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                extracted = match.group(1).strip()
                if len(extracted) >= 2:
                    return extracted
        return None
