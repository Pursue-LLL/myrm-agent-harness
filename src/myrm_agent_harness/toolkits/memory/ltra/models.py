"""Data models and contracts for Listen-Translate-Remember-Act (LTRA) cognitive pipeline.

[POS]
随身感知“听—译—记—办”全链路核心数据契约。定义声纹分段、不可篡改原声时间戳锚点、
四元组认知事实以及沙箱执行工单草稿规范。

[INPUT]
- 声纹时间戳转写切片元数据
- 商业/技术交流四元组事实元数据

[OUTPUT]
- DiarizedTranscriptSegment: 声纹说话人对齐切片契约
- AudioTimestampAnchor: 毫秒级原声溯源防篡改锚点
- CognitiveFactQuadruple: [主体][诉求][承诺][卡点]高纯度事实契约
- FollowupTaskDraft: 结构化沙箱任务执行工单契约
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class DiarizedTranscriptSegment:
    """A single transcript turn segment tagged with speaker diarization and millisecond timestamps."""

    speaker_id: str
    text: str
    start_ms: int
    end_ms: int
    speaker_name: str | None = None
    confidence: float = 1.0

    def duration_ms(self) -> int:
        """Return length of speech segment in milliseconds."""
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class AudioTimestampAnchor:
    """Immutable provenance anchor linking distilled facts to raw audio time slice."""

    audio_id: str
    start_ms: int
    end_ms: int
    verbatim_quote: str
    sha256_digest: str

    @classmethod
    def create(
        cls,
        audio_id: str,
        start_ms: int,
        end_ms: int,
        verbatim_quote: str,
    ) -> AudioTimestampAnchor:
        """Create anchor and compute integrity digest over coordinates and text."""
        raw_seed = f"{audio_id}:{start_ms}:{end_ms}:{verbatim_quote}".encode()
        digest = hashlib.sha256(raw_seed).hexdigest()[:16]
        return cls(
            audio_id=audio_id,
            start_ms=start_ms,
            end_ms=end_ms,
            verbatim_quote=verbatim_quote,
            sha256_digest=digest,
        )


@dataclass
class CognitiveFactQuadruple:
    """High-purity distilled cognitive fact quadruple from multi-party conversation."""

    fact_id: str
    subject: str
    demand: str
    commitment: str
    pending_issue: str
    anchors: list[AudioTimestampAnchor] = field(default_factory=list)
    project_id: str | None = None
    target_agent_id: str | None = None
    is_confidential: bool = False
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @classmethod
    def create(
        cls,
        subject: str,
        demand: str,
        commitment: str,
        pending_issue: str,
        anchors: list[AudioTimestampAnchor] | None = None,
        project_id: str | None = None,
        target_agent_id: str | None = None,
        is_confidential: bool = False,
    ) -> CognitiveFactQuadruple:
        """Factory constructor assigning deterministic/unique fact id."""
        fact_id = f"fact_ltra_{uuid.uuid4().hex[:12]}"
        return cls(
            fact_id=fact_id,
            subject=subject,
            demand=demand,
            commitment=commitment,
            pending_issue=pending_issue,
            anchors=anchors or [],
            project_id=project_id,
            target_agent_id=target_agent_id,
            is_confidential=is_confidential,
        )

    def to_concise_summary(self) -> str:
        """Render markdown bullet representation of distilled fact."""
        parts = [f"**主体**: {self.subject}", f"**诉求**: {self.demand}"]
        if self.commitment and self.commitment != "无":
            parts.append(f"**承诺**: {self.commitment}")
        if self.pending_issue and self.pending_issue != "无":
            parts.append(f"**待解决/卡点**: {self.pending_issue}")
        return " | ".join(parts)


@dataclass(frozen=True)
class FollowupTaskDraft:
    """Actionable sandbox task blueprint generated from confirmed conversation fact."""

    task_id: str
    source_fact_id: str
    title: str
    objective: str
    context_summary: str
    verbatim_evidence: str
    target_agent_role: str
    sandbox_deliverable_path: str
    action_plan_steps: tuple[str, ...]
    idempotency_token: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
