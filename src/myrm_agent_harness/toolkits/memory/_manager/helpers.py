"""Private helpers for MemoryManager.

[INPUT]
- memory.strategies.preference_stability::PreferenceCategory (POS: preference taxonomy)
- memory.types::SemanticMemory (POS: typed semantic memory schema)

[OUTPUT]
- _memory_ref: metadata-scoped memory ref dict
- _infer_preference_category: keyword-based preference category inference

[POS]
Internal helper functions used by governance and deletion mixins.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.preference_stability import PreferenceCategory
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


def _memory_ref(memory_id: str, metadata: dict[str, object]) -> dict[str, str]:
    ref = {"id": memory_id}
    import_item_id = metadata.get("import_item_id")
    if isinstance(import_item_id, str):
        ref["import_item_id"] = import_item_id
    return ref


def _infer_preference_category(memory: SemanticMemory) -> PreferenceCategory:
    """Infer preference category from memory content via keyword heuristics."""
    content_lower = memory.content.lower()

    category_rules: tuple[tuple[PreferenceCategory, tuple[str, ...]], ...] = (
        (PreferenceCategory.IDENTITY, ("i am", "my name", "i'm", "我是", "我的名字")),
        (
            PreferenceCategory.VETO,
            ("don't", "never", "hate", "avoid", "禁止", "不要", "讨厌", "refuse"),
        ),
        (
            PreferenceCategory.CHANNEL,
            ("channel", "email", "slack", "wechat", "discord", "渠道", "邮件"),
        ),
        (PreferenceCategory.GOAL, ("goal", "plan", "want to", "aim", "目标", "计划")),
        (
            PreferenceCategory.TOOLING,
            ("use ", "tool", "ide", "editor", "framework", "工具", "使用"),
        ),
    )

    for category, keywords in category_rules:
        if any(kw in content_lower for kw in keywords):
            return category

    return PreferenceCategory.STYLE
