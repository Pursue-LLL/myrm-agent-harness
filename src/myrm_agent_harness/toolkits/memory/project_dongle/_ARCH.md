# Project Context USB Dongle Architecture (`project_dongle`)

## 1. 架构定位
本模块实现路线图 Item 152 `ProjectContextUsbDongleAndCrossAgentRelaySuite`，提供项目工作区四维纯文本记忆块协议（`PROJECT_STATE.md`、`DECISIONS.md`、`LESSONS.md`、`INDEX.md`）、Bullet 块版本化解析、超限指针归档（`*_ARCHIVE.md`）与跨 Agent 确定性上下文热插拔无损装载。

## 2. 模块文件表
| 文件 | 职责 |
|---|---|
| `models.py` | 核心域模型（`DongleBlockType`, `DongleBlock`, `DongleArchivePointer`, `DongleState`, `SyncResult`） |
| `block_parser.py` | 纯文本 Markdown 结构解析器与规范化渲染器（`parse_blocks`, `render_file`） |
| `archive_spill.py` | 超限溢出指针归档管理器（`ArchiveSpillManager`） |
| `dongle_manager.py` | 四维记忆块文件系统协调器与上下文渲染引擎（`ProjectContextDongleManager`） |
| `__init__.py` | 包门面导出 |
