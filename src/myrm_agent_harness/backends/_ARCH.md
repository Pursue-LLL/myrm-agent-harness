# backends/

## Overview
Backend implementations — profiles, secrets, and skills storage adapters between harness core and agent runtime.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Import guide only; use subpackages (`backends.profiles`, `backends.secrets`, `backends.skills`) or `api.protocols`. | — |

| Submodule | Description |
|-----------|-------------|
| profiles/ | Agent Profile 存储后端。AgentProfile 数据结构、CRUD Protocol、Local/InMemory 实现。 |
| secrets/ | Agent 密钥/凭据存储后端。AgentSecretBackend Protocol、Local 加密文件 / InMemory 实现。 |
| skills/ | 技能系统后端。读/写/发现 Protocol、Local/Memory/Storage 实现、快照缓存与安全扫描。 |

## Key Dependencies

- `infra` (delivery, locks)
- `utils` (crypto, db, coercion)
- `toolkits` (storage, channels.core.exceptions for exception hierarchy)

## Public API

Extension-point Protocols are re-exported from `myrm_agent_harness.api.protocols`:
`SkillBackend`, `AgentProfileBackend`, `AgentSecretBackend`.
