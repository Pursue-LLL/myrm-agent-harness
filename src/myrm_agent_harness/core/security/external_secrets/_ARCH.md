# core/security/external_secrets/

## Overview
外部企业级密码管理器（1Password `op://`、Bitwarden `bw://` / `bws://`）零落盘凭据解析与动态轮换域。
支持内存级 LRU + TTL 缓存、单飞（Single-Flight）并发保护、非交互式子进程隔离与 401 缓存失效自愈。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 统一门面与便捷函数导出（`resolve_external_secret`、`invalidate_external_secret`） | ✅ |
| `protocols.py` | Core | `ExternalSecretResolver` Protocol 与 `ResolverHealth` 契约定义 | ✅ |
| `manager.py` | Impl | `ExternalSecretsManager` 单例实现：LRU 缓存、Single-Flight、非交互环境变量、401 驱逐 | ✅ |

## Key Dependencies
- Standard library (`subprocess`, `threading`, `json`, `time`, `os`, `re`)
- 零外部三方依赖，纯单机无耦合

## Consumers
- `myrm_agent_harness.core.security.safe_exec` — 自动置换 Sentinel Voucher
- `myrm_agent_harness.backends.secrets` — 统一重导出门面
- `myrm_agent_harness.toolkits.llms.secrets` — 保持兼容重导出
- `myrm-agent-server.app.services.agent.backends.secret_backend` — MCP 与 Agent 凭据解算
- `myrm-agent-server.app.api.integrations.credential_pool` — 连通性测试 API
