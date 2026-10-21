# cli_adapter/

## 架构概述

多源异构 Agent 外部进程桥接与 CLI 工具标准化适配器（Heterogeneous External Agent Bridge & CLI Process Adapter）。
支持在系统中无缝挂载外部独立的命令行 Agent（如 Claude Code CLI、Codex CLI、OpenClaw 或通用 Stdio 进程），提供进程生命周期管理、超时熔断（SIGTERM -> SIGKILL 升级）、ANSI 控制序列安全清洗转义以及防篡改的 SHA-256 执行凭证收据（ProcessReceipt）。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 门面导出：导出异构 Agent 种类枚举、数据契约、流清洗器与 CLI 进程适配器 | ✅ |
| `types.py` | 核心 | 强类型契约：定义 `ExternalAgentKind`、`ProcessLaneStatus`、`ExternalAgentConfig`、`ProcessReceipt` 与 `ProcessExecutionRequest` | ✅ |
| `stream_cleaner.py` | 核心 | 流清洗与证据哈希：安全剥离 ANSI 转义字符与破坏性 C0 控制符，进行安全有界截断，生成确定性 SHA-256 证据哈希 | ✅ |
| `adapter.py` | 核心 | 进程调度与凭证管理：实现 `ExternalCliAgentAdapter`，负责外部 CLI 进程拉起、Stdio 管道交互、超时优雅停机与历史凭据维护 | ✅ |
