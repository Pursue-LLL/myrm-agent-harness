# file_sync 模块架构设计

## 模块架构概览

提供基于本地标准化 Markdown 文件的长期记忆存储与双向增量同步引擎。
支持人类可读的 `MEMORY.md` 核心记忆与 `memory/daily/` 每日笔记管理，提供精准的物理行号锚点溯源。

详细设计请参考父目录技术方案 [../MEMORY_SYSTEM.md](../MEMORY_SYSTEM.md)。

## 文件清单与职责

| 文件 | 地位 | 职责 | I/O/P |
| :--- | :---: | :--- | :---: |
| `__init__.py` | 门面 | 子包公共符号导出与统一入口 | ✅ |
| `models.py` | 核心 | 记忆条目、目录拓扑与同步报告领域模型 | ✅ |
| `parser.py` | 核心 | 宽容 Markdown 流式状态机解析器与行号提取 | ✅ |
| `store.py` | 核心 | 物理 Markdown 存储器与临时文件原子写入（`os.replace`） | ✅ |
| `anchor.py` | 辅助 | 溯源标签与上下文格式化器（`[source: file#Lstart-Lend]`） | ✅ |
| `sync.py` | 核心 | 双向增量同步协调引擎与惰性保鲜探针 | ✅ |

## 模块依赖

- 内部依赖：`models.py` <- `parser.py`, `store.py`, `anchor.py`, `sync.py`
- 外部依赖：`myrm_agent_harness.toolkits.memory.manager::MemoryManager`
