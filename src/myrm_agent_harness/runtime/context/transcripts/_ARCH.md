# runtime/context/transcripts 模块架构

## 架构概览

跨助手会话转录本纯净解析与连续性重锚引擎。为 Claude Code、Codex CLI 等外部历史会话提供流式去噪解析、沙箱工作区路径重锚（`/workspace`）与两阶段工具输出紧凑规约。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面导出解析器、路径重锚器、规约器与规范数据结构 | ✅ |
| `types.py` | 核心 | 统一多轮对话数据模型（`CanonicalTranscriptTurn`、`CanonicalToolCall`、`TranscriptParseResult`） | ✅ |
| `claude_parser.py` | 核心 | Claude Code JSONL 会话流逐行解析、ThinkingTrace 提取与工具调用挂接 | ✅ |
| `codex_parser.py` | 核心 | OpenAI Codex CLI JSON 会话解析与结构化工具映射 | ✅ |
| `path_remapper.py` | 辅助 | 宿主机物理绝对路径到沙箱工作区（`/workspace`）的自动重锚替换 | ✅ |
| `tool_compactor.py` | 辅助 | 两阶段工具输出紧凑规约（超阈值首尾保留），防止首轮续聊上下文爆仓 | ✅ |

## 模块依赖

- 内部依赖：标准库 `json`, `logging`, `pathlib`, `re`, `dataclasses`, `enum`, `typing`
- 外部依赖：无（纯 Python 无状态轻量解析，零外部重型依赖）
