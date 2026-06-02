"""Session Notes 数据结构

[INPUT]

[OUTPUT]
- NoteSection: 笔记 section 数据类
- SessionNotes: 完整会话笔记数据类
- SessionNotesConfig: 笔记配置数据类
- DEFAULT_SECTIONS: 默认 section 列表
- DEFAULT_SESSION_NOTES_CONFIG: 默认配置

[POS]
Session Notes type system foundation. Defines structured data models for notes, section templates, and configuration constants.

"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class NoteSection:
    """笔记 section

    Attributes:
        key: section 标识符（用于增量合并时的 key 匹配）
        title: 显示标题
        description: section 说明（给 LLM 看的，指导写什么内容）
        content: 实际内容
        max_tokens: 单 section token 上限
    """

    key: str
    title: str
    description: str
    content: str = ""
    max_tokens: int = 2000


DEFAULT_SECTIONS: list[NoteSection] = [
    NoteSection(
        key="session_title",
        title="Session Title",
        description="A short and distinctive 5-10 word descriptive title. Super info dense, no filler.",
        max_tokens=100,
    ),
    NoteSection(
        key="current_state",
        title="Current State",
        description="What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps.",
        max_tokens=2000,
    ),
    NoteSection(
        key="task_spec",
        title="Task Specification",
        description="What did the user ask to build? Any design decisions or other explanatory context.",
        max_tokens=2000,
    ),
    NoteSection(
        key="files_and_functions",
        title="Files and Functions",
        description="Important files, what they contain, why they are relevant, and how they interact or fit together. Include paths and key function names.",
        max_tokens=2000,
    ),
    NoteSection(
        key="workflow",
        title="Workflow",
        description="What commands are usually run and in what order? How to interpret their output if not obvious?",
        max_tokens=1500,
    ),
    NoteSection(
        key="errors_and_corrections",
        title="Errors & Corrections",
        description="Errors encountered and how they were fixed. What the user corrected. What approaches failed and should not be tried again.",
        max_tokens=1500,
    ),
    NoteSection(
        key="key_findings",
        title="Key Findings",
        description="Important discoveries, conclusions, and results. If the user asked a specific question, include the exact answer.",
        max_tokens=1500,
    ),
    NoteSection(
        key="worklog",
        title="Worklog",
        description="Step by step, what was attempted and done. Very terse summary for each step.",
        max_tokens=1500,
    ),
]

TOTAL_MAX_TOKENS = 12000

REQUIRED_SECTIONS_FOR_READY = frozenset({"current_state", "task_spec"})

MIN_READY_TOKENS = 500


@dataclass
class SessionNotesConfig:
    """Session Notes 配置

    Attributes:
        init_token_threshold: 总 token 达到此值才开始维护笔记（避免短对话浪费）
        update_token_threshold: 上次更新后 token 增长达到此值才触发更新
        update_tool_call_threshold: 上次更新后工具调用次数达到此值才触发更新
        full_refresh_interval: 每 N 次增量合并后做一次全量刷新
        max_consecutive_failures: 连续失败 N 次后触发断路器
        circuit_breaker_cooldown_seconds: 熔断后自动恢复的冷却时间（秒）
        wait_timeout_seconds: 压缩时等待笔记更新完成的超时时间
        total_max_tokens: 笔记总 token 上限
    """

    init_token_threshold: int = 8000
    update_token_threshold: int = 5000
    update_tool_call_threshold: int = 3
    full_refresh_interval: int = 5
    max_consecutive_failures: int = 3
    circuit_breaker_cooldown_seconds: int = 1800  # 30 minutes
    wait_timeout_seconds: float = 10.0
    total_max_tokens: int = TOTAL_MAX_TOKENS


DEFAULT_SESSION_NOTES_CONFIG = SessionNotesConfig()


@dataclass
class SessionNotes:
    """完整会话笔记

    Attributes:
        sections: section 列表
        last_updated_message_idx: 上次更新时的消息索引（用于增量合并时确定新消息范围）
        incremental_count: 自上次全量刷新以来的增量合并次数
        config: 笔记配置
    """

    sections: list[NoteSection] = field(default_factory=lambda: [_clone_section(s) for s in DEFAULT_SECTIONS])
    last_updated_message_idx: int = 0
    incremental_count: int = 0
    config: SessionNotesConfig = field(default_factory=lambda: SessionNotesConfig())

    def is_ready(self) -> bool:
        """笔记是否已就绪（可用于替代 LLM 摘要）

        条件：关键 section 有内容 + 总 token 达到最低阈值
        """
        for section in self.sections:
            if section.key in REQUIRED_SECTIONS_FOR_READY and not section.content.strip():
                return False
        return self.estimate_total_tokens() >= MIN_READY_TOKENS

    def estimate_total_tokens(self) -> int:
        """估算笔记总 token 数（粗略：字符数 / 4）"""
        total = 0
        for section in self.sections:
            total += len(section.content) // 4
        return total

    def to_summary_text(self) -> str:
        """转换为摘要文本（用于压缩时替代 LLM 摘要）"""
        parts: list[str] = []
        for section in self.sections:
            if section.content.strip():
                parts.append(f"## {section.title}\n{section.content.strip()}")
        return "\n\n".join(parts)

    def to_json(self) -> str:
        """序列化为 JSON（用于增量合并 prompt 和 DB 持久化）

        包含 _meta 字段保存 last_updated_message_idx 和 incremental_count，
        确保会话恢复时能精确继续增量更新。
        """
        data: dict[str, object] = {}
        for section in self.sections:
            data[section.key] = section.content
        data["_meta"] = {
            "last_updated_message_idx": self.last_updated_message_idx,
            "incremental_count": self.incremental_count,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str, config: SessionNotesConfig | None = None) -> SessionNotes:
        """从 JSON 反序列化（用于从 DB 加载）"""
        data = json.loads(json_str)
        cfg = config or SessionNotesConfig()
        notes = cls(config=cfg)

        meta = data.pop("_meta", None)
        if isinstance(meta, dict):
            notes.last_updated_message_idx = int(meta.get("last_updated_message_idx", 0))
            notes.incremental_count = int(meta.get("incremental_count", 0))

        section_map = {s.key: s for s in notes.sections}
        for key, content in data.items():
            if key in section_map and isinstance(content, str):
                section_map[key].content = content
        return notes

    def get_section(self, key: str) -> NoteSection | None:
        """按 key 获取 section"""
        for section in self.sections:
            if section.key == key:
                return section
        return None

    def truncate_for_compact(self) -> tuple[str, bool]:
        """截断超限 section 后返回摘要文本

        Returns:
            (truncated_text, was_truncated)
        """
        was_truncated = False
        parts: list[str] = []
        for section in self.sections:
            content = section.content.strip()
            if not content:
                continue
            char_limit = section.max_tokens * 4
            if len(content) > char_limit:
                content = content[:char_limit] + "\n[... section truncated for length ...]"
                was_truncated = True
            parts.append(f"## {section.title}\n{content}")
        return "\n\n".join(parts), was_truncated

    def needs_full_refresh(self) -> bool:
        """是否需要全量刷新（防止增量合并的信息漂移）"""
        return self.incremental_count >= self.config.full_refresh_interval


def _clone_section(s: NoteSection) -> NoteSection:
    return NoteSection(key=s.key, title=s.title, description=s.description, content=s.content, max_tokens=s.max_tokens)
