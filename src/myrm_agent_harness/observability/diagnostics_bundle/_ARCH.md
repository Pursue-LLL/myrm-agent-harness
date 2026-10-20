# observability/diagnostics_bundle/

## Overview
端内沙箱现场全景诊断打包与自愈凭证引擎（In-App Live Diagnostics & Self-Healing Dossier）。
负责在沙箱发生断连、进程死锁、OOM、或网络异常中断时，收集系统生命体征、内核事件、客户端状态，执行严格的 PII/密钥脱敏（Authorization Header、Bearer Token、sk-xxx 等掩码处理），生成防篡改 HMAC 校验和全景诊断包，为后续闪电工单上报与就地自愈提供完整取证依据。

## File & Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | 导出诊断包模型结构体与打包引擎门面。 | ✅ |
| `models.py` | Data Contracts | 定义 `DiagnosticLogEvent`、`SandboxVitals`、`ClientContext` 与 `EncryptedDiagnosticBundle` 不可变数据契约。 | ✅ |
| `packager.py` | Core Engine | 实现 `DiagnosticBundlePackager`，提供多模态正则 PII/Secret 深度脱敏、日志截断限制及 HMAC-SHA256 签名校验。 | ✅ |

## Architectural Constraints
1. **零 Any 类型**：严格采用明确强类型与 Dataclass 模式。
2. **安全隔离**：严禁泄露明文密钥、用户凭证及个人隐私信息，所有敏感字段进入 Bundle 前必须被正则抹除。
3. **数据一致性**：Bundle 生成规范化 JSON 序列化，配合 HMAC-SHA256 确保运维接收时现场完整性未被伪造或篡改。
