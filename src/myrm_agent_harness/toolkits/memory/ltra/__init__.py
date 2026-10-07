"""Listen-Translate-Remember-Act (LTRA) cognitive pipeline package.

[POS]
随身感知“听—译—记—办”认知流转子系统统一导出入口。

[INPUT]
- models, identity_resolver, guard, distillation_worker, task_builder

[OUTPUT]
- 统一公开的 LTRA 核心类型与工作器
"""

from __future__ import annotations

from .distillation_worker import AudioFactDistillationWorker
from .guard import SensitiveAudioFactGuard
from .identity_resolver import SpeakerIdentityResolver
from .models import (
    AudioTimestampAnchor,
    CognitiveFactQuadruple,
    DiarizedTranscriptSegment,
    FollowupTaskDraft,
)
from .task_builder import FollowupTaskDraftBuilder

__all__ = [
    "DiarizedTranscriptSegment",
    "AudioTimestampAnchor",
    "CognitiveFactQuadruple",
    "FollowupTaskDraft",
    "SpeakerIdentityResolver",
    "SensitiveAudioFactGuard",
    "AudioFactDistillationWorker",
    "FollowupTaskDraftBuilder",
]
