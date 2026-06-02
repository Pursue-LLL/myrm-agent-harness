# toolkits/workspace


## 架构概述

通用 workspace 路径建议工具包。只负责单机文件系统枚举、路径安全过滤和模糊排序；不包含 HTTP、chat_id、GUI 状态、多租户或业务存储语义。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 导出 workspace suggestion 公共 API | ✅ |
| `indexer.py` | 核心 | 有界文件枚举。优先 `git ls-files --cached --others --exclude-standard`，降级 `os.walk`，带短 TTL 缓存 | ✅ |
| `models.py` | 核心 | Workspace suggestion DTO 与选项模型 | ✅ |
| `suggest.py` | 核心 | GUI 友好的文件/目录建议排序；支持 basename 模糊匹配和 slash/path 目录模式 | ✅ |
