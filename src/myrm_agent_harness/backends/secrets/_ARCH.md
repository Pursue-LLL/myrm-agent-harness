# secrets/

## Overview
Agent 密钥/凭据存储后端 — 定义 AgentSecretBackend Protocol 及 Local（AES-256-GCM 加密文件）/ InMemory 开箱即用实现。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 统一导出 secrets 模块公开 API | ✅ |
| `protocols.py` | Core | AgentSecretBackend Protocol（get/set/delete/list CRUD 契约） | ✅ |
| `local_backend.py` | Impl | 本地加密文件持久化（.secrets.enc + ConfigCrypto） | ✅ |
| `memory_backend.py` | Impl | Dict-backed 内存实现（测试 / 临时场景） | ✅ |
| `command_backend.py` | Impl | 外部命令 Helper 动态拉取（Zero-Disk Plaintext / pass / 1Password / Bitwarden） | ✅ |
| `external_resolver.py` | Impl | 外部凭据 URI 解析器（op:// 与 bw:// 协议零落盘内存解析） | ✅ |

## Key Dependencies

- `utils.crypto` (ConfigCrypto, DecryptionError, EncryptionError)
