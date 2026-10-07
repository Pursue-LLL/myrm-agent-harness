"""Speaker identity and alias resolution module for LTRA pipeline.

[POS]
随身感知声纹说话人与业务身份对齐解析器。将 STT 声纹分离输出的抽象标号
（如 Speaker_0 / Speaker_1）映射为高语义的业务角色名（如“张总(客户决策人)”）。

[INPUT]
- Speaker ID 标号与段落文本
- 外部预设映射字典或上下文启发式命名规则

[OUTPUT]
- SpeakerIdentityResolver: 说话人身份映射与自动识别引擎
"""

from __future__ import annotations

import re


class SpeakerIdentityResolver:
    """Resolves raw acoustic speaker tokens to meaningful business participant titles."""

    # Common self-introduction conversational markers in Chinese & English
    _INTRO_PATTERNS = (
        re.compile(r"(?:我叫|我是|鄙人是|我代表)\s*([A-Za-z\u4e00-\u9fa5]{2,8})", re.IGNORECASE),
        re.compile(r"(?:i am|this is|my name is)\s+([A-Za-z\s]{2,20})", re.IGNORECASE),
    )

    def __init__(self, initial_aliases: dict[str, str] | None = None) -> None:
        """Initialize resolver with optional manual speaker mapping dictionary."""
        self._alias_map: dict[str, str] = dict(initial_aliases or {})

    def register_alias(self, speaker_id: str, human_name: str) -> None:
        """Explicitly bind a raw speaker id to a human/business identity."""
        cleaned_id = speaker_id.strip()
        cleaned_name = human_name.strip()
        if cleaned_id and cleaned_name:
            self._alias_map[cleaned_id] = cleaned_name

    def register_bulk(self, mapping: dict[str, str]) -> None:
        """Register multiple speaker mappings at once."""
        for speaker_id, name in mapping.items():
            self.register_alias(speaker_id, name)

    def resolve(self, speaker_id: str, segment_text: str | None = None) -> str:
        """Resolve speaker name using explicit mappings, heuristic mining, or safe fallback."""
        cleaned_id = speaker_id.strip()
        if cleaned_id in self._alias_map:
            return self._alias_map[cleaned_id]

        # Heuristic self-introduction discovery
        if segment_text:
            inferred = self._mine_speaker_intro(segment_text)
            if inferred:
                self._alias_map[cleaned_id] = inferred
                return inferred

        # Default fallback
        if not cleaned_id or cleaned_id.lower() in {"unknown", "speaker_unknown", ""}:
            return "参会人员"
        return cleaned_id

    def get_all_mappings(self) -> dict[str, str]:
        """Return snapshot of currently recognized speaker mappings."""
        return dict(self._alias_map)

    def _mine_speaker_intro(self, text: str) -> str | None:
        """Inspect beginning of sentence for introductory speech tokens."""
        sample = text[:80]
        for pattern in self._INTRO_PATTERNS:
            match = pattern.search(sample)
            if match:
                candidate = match.group(1).strip()
                if 2 <= len(candidate) <= 12:
                    return candidate
        return None
