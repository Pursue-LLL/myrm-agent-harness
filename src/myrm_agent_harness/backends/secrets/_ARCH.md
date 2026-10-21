# secrets/

## Overview
Agent 密钥/凭据存储契约 — 定义 AgentSecretBackend Protocol；存储实现由宿主提供。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 统一导出 secrets 模块公开 API | ✅ |
| `protocols.py` | Core | AgentSecretBackend Protocol（get/set/delete/list CRUD 契约） | ✅ |
