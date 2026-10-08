# chunking/ 架构说明

## 模块定位
Item 132 `IncrementalSlidingWindowMarkdownChunkerSuite`（增量滑动窗口Markdown切片与重叠索引管道套件）。
提供 400 token 目标块 + 80 token 重叠切片、内容哈希增量感知、代码块边界保护、源文件行号回溯指针与 Token 节省率分析。
另含对话切片策略（`conversation.py`）：把消息序列按交换对 / 仅用户 / 整会话 / 情景切成语义单元，供原文存储、记忆迁移与抽取使用。

## 文件清单

| 文件名 | 职责 |
|---|---|
| `__init__.py` | 包门面导出，导出数据契约、切片引擎、回溯水合器、增量管道与对话切片策略 |
| `models.py` | 强类型数据契约：ChunkingConfig, MarkdownChunk, IncrementalDiffReport |
| `chunker.py` | 语义滑动窗口切片引擎：400 token 目标容量、80 token 重叠、代码块边界保护与行级指针跟踪 |
| `hydrator.py` | 上下文回溯水合器：基于 start_line / end_line 指针从源文档或本地文件还原周边上下文 |
| `pipeline.py` | 增量差量索引管道：内容哈希追踪、复用未变动向量、仅对增量差异触发向量化并统计 Token 节省率 |
| `conversation.py` | 对话切片策略：`ChunkingStrategy`（交换对 / 仅用户 / 整会话 / 情景）、`ConversationChunk`、按空闲间隔与上下文预算切分并带因果滑动重叠的 `EpisodesChunker`，入口 `chunk_conversation()` |
