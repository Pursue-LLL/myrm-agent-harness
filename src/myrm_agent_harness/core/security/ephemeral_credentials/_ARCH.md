# core/security/ephemeral_credentials 架构说明

## 架构概览

会话隔离瞬态凭证存储与内存物理归零引擎。为执行环境敏感凭据提供阅后即焚、TTL 过期回收与内存安全清零保证。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 核心 | 导出瞬态凭证模型、摘要对象与存储管理器单例入口 | ✅ |
| `store.py` | 核心 | 会话隔离内存凭据保险库、线程安全存取、TTL 扫描与会话级批量清理 | ✅ |
| `types.py` | 核心 | 凭据模型定义、密钥命名白名单校验与内存物理覆写清零实现 | ✅ |

## 模块依赖

- 内部依赖：`core/security/ephemeral_credentials/types.py`
- 外部依赖：标准库 `dataclasses`, `logging`, `re`, `threading`, `time`, `uuid`
