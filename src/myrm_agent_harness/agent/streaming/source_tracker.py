"""会话级引用源追踪器

[INPUT]

[OUTPUT]
- SourceTracker: 会话级引用源追踪（去重 + 全局编号 + 增量返回）

[POS]
Source reference forwarding capability for BaseAgent.

"""

from __future__ import annotations

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SourceTracker:
    """会话级引用源追踪器

    职责：
    - URL 级去重（带 url 的来源按 url 去重）
    - 内容级去重（无 url 的来源按全字段哈希去重）
    - 全局编号（跨多次工具调用保持唯一递增 index）
    - 增量返回（add_batch 只返回本次新增的来源）

    工具接入方式：
    在工具返回值中包含 metadata.sources 字段即可，框架自动处理。
    """

    def __init__(self) -> None:
        self._seen_keys: dict[str, int] = {}
        self._all_sources: list[dict[str, object]] = []
        self._next_index = 1

    def add_batch(self, raw_sources: list[dict[str, object]]) -> list[dict[str, object]]:
        """添加一批来源，返回去重后的新增来源（已分配全局 index）"""
        new_items: list[dict[str, object]] = []
        for src in raw_sources:
            if not isinstance(src, dict):
                continue
            key = self._dedup_key(src)
            if key in self._seen_keys:
                continue

            item = {**src, "index": self._next_index}
            self._seen_keys[key] = self._next_index
            self._all_sources.append(item)
            new_items.append(item)
            self._next_index += 1

        if new_items:
            logger.debug(" SourceTracker: +%d new (total %d)", len(new_items), len(self._all_sources))
        return new_items

    def extract_and_add(self, metadata: dict[str, object]) -> list[dict[str, object]]:
        """从工具元数据中提取 sources 并添加"""
        sources = metadata.get("sources")
        if isinstance(sources, list) and sources:
            return self.add_batch(sources)
        return []

    @property
    def all_sources(self) -> list[dict[str, object]]:
        """获取当前所有去重后的来源（含全局 index）"""
        return self._all_sources.copy()

    def _dedup_key(self, src: dict[str, object]) -> str:
        """生成去重键（纯通用，不硬编码任何业务字段）

        策略：
        1. 有 url → 按 url 去重（最常见）
        2. 否则 → 按所有非 index 字段的内容哈希去重
        """
        if url := src.get("url"):
            return f"url:{url}"
        stable = sorted((k, str(v)) for k, v in src.items() if k != "index")
        return f"content:{hash(tuple(stable))}"
