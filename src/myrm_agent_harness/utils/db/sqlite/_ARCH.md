# db/sqlite/

## 架构概述
统一的 SQLite 硬化工厂：每个 store 通过它打开连接，获得一致的持久化 / 隐私 /
并发 / 崩溃恢复保障（声明式 Profile + 连接硬化 + 文件级完整性守卫）。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 对外导出 Profile 预设、连接硬化与完整性原语 | ✅ |
| `profile.py` | 配置 | 冻结的 `SQLiteProfile` PRAGMA 规格与五档预设（`DEFAULT`/`DURABLE`/`SENSITIVE`/`CACHE`/`READONLY`） | ✅ |
| `integrity.py` | 叶子 | 文件级守卫与崩溃恢复：header magic 校验、`page_count` 截断不变量、孤儿 WAL 清理、有界 `quick_check_sync`、WAL `checkpoint_truncate`、`prepare_database_file` | ✅ |
| `hardening.py` | 核心 | `harden_connection_sync/async`（应用 Profile，返回 journal 模式）、`connect_async` 上下文管理器、`should_fallback_to_delete`（WAL→DELETE 降级的唯一决策真源） | ✅ |

## 模块依赖
- `hardening.py` → `profile.py`、`integrity.py`（叶子，无内部反向依赖）
- 消费方：harness 内全部 SQLite store；业务层 `myrm-agent-server/app/database/factory.py`
  的 SQLAlchemy 监听复用 `should_fallback_to_delete`，使主库共享同一 EIO 安全回退契约。

## 关键契约
- **EIO 安全回退**：仅当错误确定性地表明文件系统不支持 WAL 时才永久降级为 DELETE；
  当 on-disk header 证明数据库已是 WAL 时绝不降级（瞬时 I/O 错误保持 WAL）。
- **撕裂写守卫**：`cell_size_check=ON` 早检测 B-tree 撕裂；`page_count` 不变量检测物理截断。
- **隐私**：`SENSITIVE` 档 `secure_delete=ON`，删除即抹零（用于 PII 假名库）。
