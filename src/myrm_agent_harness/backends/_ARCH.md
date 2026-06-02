# backends/

## Overview
Backend implementations — profiles, secrets, and skills adapters.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Backend implementations — profiles, secrets, and skills adapters. | — |

| Submodule | Description |
|-----------|-------------|
| profiles/ | Agent Profile 存储后端。定义 AgentProfile 数据结构、Protocol 及 Local/InMemory 实现。 |
| secrets/ | Agent Secrets Backend Module. |
| skills/ | Skill backend implementations module. Provides multiple backend implementations and three core protocols. |

## Key Dependencies

- `infra` (delivery, locks)
- `utils` (crypto, db, coercion)
- `toolkits` (storage, channels.core.exceptions for exception hierarchy)
