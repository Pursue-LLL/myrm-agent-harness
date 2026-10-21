# backends/

## Overview
Backend implementations — profiles, secrets, and skills storage adapters between harness core and agent runtime.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Import guide only; use subpackages (`backends.profiles`, `backends.secrets`, `backends.skills`) or `api.protocols`. | — |

| Submodule | Description |
|-----------|-------------|
| profiles/ | Agent Profile 契约。AgentProfile 数据结构与 CRUD Protocol，存储实现由宿主提供。 |
| secrets/ | Agent 密钥/凭据存储契约。AgentSecretBackend Protocol，存储实现由宿主提供。 |
| skills/ | 技能系统后端。读/写/发现 Protocol、Local/Memory/Storage 实现、快照缓存与安全扫描。 |
| commerce/ | 商业智能体双端后端契约。StorefrontBackend (C端) 与 MerchantBackend (B端) 核心协议与 DTOs，实现由宿主提供。 |

## Key Dependencies

- `infra` (atomic_write, tls_compat)
- `utils` (crypto, db, coercion)
- `toolkits` (storage, channels.core.exceptions for exception hierarchy)

## Public API

Extension-point Protocols are re-exported from `myrm_agent_harness.api.protocols`:
`SkillBackend`, `AgentProfileBackend`, `AgentSecretBackend`.
