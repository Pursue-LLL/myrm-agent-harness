# sanitized_debug_dump/

## 架构概述

一键安全脱敏诊断包生成、敏感凭据物理抹除与加密阅后即焚分享管理包。上级文档：[../_ARCH.md](../_ARCH.md)。
聚焦彻底消灭用户排障时面临的终端生涩命令与私有密钥、绝对路径泄漏的隐私隐患：
1. **物理级凭据正则脱敏网关 (Zero-Leak Redactor)**：自动识别并物理抹除 API Key (OpenAI / Anthropic / GitHub)、Bearer Token、本地用户 Home 目录绝对路径、IP 地址与邮箱；
2. **安全诊断打包器 (Sanitized Debug Packager)**：收集系统环境体征 (OS / Python / CPU / 内存)、清洗 Trace 与现场堆栈，计算防篡改 SHA-256 校验和；
3. **阅后即焚分享短链 (Ephemeral Share Link)**：支持生成具备生命周期的排障短链（默认 48 小时有效，访问 3 次后自动粉碎自毁）。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 实体 | 定义 RedactionRuleType, RedactionAuditRecord, SanitizedDebugDump 与 EphemeralShareLink 模型 | ✅ |
| `redactor.py` | 核心 | 敏感凭据物理级多维正则深度抹除与脱敏计数审计引擎 | ✅ |
| `packager.py` | 服务 | 系统体征快照抓取、全链路诊断打包与阅后即焚分享生命周期管理 | ✅ |
| `__init__.py` | 门面 | 聚合导出模块内所有组件与契约 | ✅ |
