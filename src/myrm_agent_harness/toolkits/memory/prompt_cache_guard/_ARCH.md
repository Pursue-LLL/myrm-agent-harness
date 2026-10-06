# prompt_cache_guard/

## 架构概述

前缀缓存稳定守卫与常驻记忆不可变快照套件（InContextFrozenSnapshotAndPromptCacheStabilityGuard）。
遵循《Hermes 记忆系统》最佳实践，根除会话中途写入记忆导致 System Prompt 前缀发生变化引发的前缀缓存崩溃（Prompt Cache Miss）与首字延迟暴增。

上级文档：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面导出不可变快照模型、容量配置、异常合约、安全扫描器、生命周期提供者与无读工具集 | ✅ |
| `models.py` | 核心 | `CapacityLimitConfig` (MEMORY ~2200c, USER ~1375c 紧凑上限)、`FrozenMemorySnapshot` (不可变常驻快照模型)、`CapacityOverflowError` (容量超限显式语义决策异常)、`SecurityThreatBlockedError` | ✅ |
| `security_gate.py` | 核心 | `ZeroWidthAndCredentialLeakScanner`：不可见零宽 Unicode 深度探测剥离、API Key/高危凭证硬拦截、精确重复过滤 | ✅ |
| `snapshot_provider.py` | 核心 | `FrozenMemorySnapshotProvider`：会话不可变快照生成绑定与 `pending_next_session` 变更隔离管理，活跃快照字节级锁定，零缓存断裂 | ✅ |
| `read_free_tools.py` | 核心 | `ReadFreeMemoryToolSuite`：无读协议工具集（提供 `memory_add`, `memory_atomic_replace`, `memory_remove`，不提供单独 read），集成安全与容量超限显式决策门禁 | ✅ |
