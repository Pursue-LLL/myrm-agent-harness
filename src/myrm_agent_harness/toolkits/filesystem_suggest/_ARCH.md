# toolkits/filesystem_suggest


## 架构概述

通用 **本地路径建议** 工具包（聊天 `@` 引用补全的后端原语）。只负责单机文件系统枚举、路径安全过滤和模糊排序；不包含 HTTP、chat_id、GUI 状态、多租户或业务存储语义。

命名说明：顶层包名 `filesystem_suggest` 刻意与 `code_execution/workspace/`（沙箱会话生命周期）及 storage 卷 `/workspace` 区分，避免「workspace」语义撞车。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 导出 path suggestion 公共 API | ✅ |
| `indexer.py` | 核心 | 有界文件枚举。优先 `git ls-files --cached --others --exclude-standard`，降级 `os.walk`，带短 TTL 缓存 | ✅ |
| `models.py` | 核心 | Workspace suggestion DTO 与选项模型 | ✅ |
| `suggest.py` | 核心 | GUI 友好的文件/目录建议排序；支持 basename 模糊匹配和 slash/path 目录模式 | ✅ |

## 消费方

| 层 | 位置 | 用途 |
|----|------|------|
| Server REST | `myrm-agent-server/app/api/files/suggest.py` | `GET /api/v1/files/suggest` — 聊天框 `@` 引用补全 |
| Frontend | `services/chat.ts` | 调用上述 API |

**非 Agent 工具**：无 `*_agent_tools.py`，不进 tool registry，零 LLM token 占用。
