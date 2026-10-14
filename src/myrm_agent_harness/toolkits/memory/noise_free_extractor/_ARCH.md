# noise_free_extractor/

## 架构概述

工具回执噪声剥离式异步记忆提炼、PII 清洗网关与单调递增清除代次套件 (Item 88, P0)。
汲取 Anthropic Commerce Agents (`commerce_common/memory.py`) 记忆隔离与 `purge_generation` 设计，彻底解决三大痛点：
1. **工具噪声污染**：`ToolNoiseFilter` 物理剥离 tool_call、tool_result 与营销 JSON 代码块，确保提取器仅分析自然语言对话；
2. **PII 与合规泄漏**：`PIISafetyGateway` 读取隐私管线（`core/security/detection`）的检测器，硬拦截银行卡、IBAN、身份证、SSN、密码与 API 密钥，提供 Reject 与 Masking 模式；它是存储硬门，不受用户隐私策略开关影响，且按存储的口径更严（15/16 位通过 Luhn 即视为银行卡，校验位写错的身份证/IBAN 仍拦截，裸 `secret:` 标签后的值视为凭据）；
3. **幽灵记忆死灰复燃**：`PurgeGenerationEpochManager` 维护用户级单调递增 `purge_generation`，后台异步写回时核验代次，过期自动丢弃。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `types.py` | 实体 | 纯净对话消息、PII 违规详情、代次状态与候选事实 DTO | ✅ |
| `noise_filter.py` | 核心 | 工具回执物理剥离预处理器（ToolNoiseFilter） | ✅ |
| `pii_gateway.py` | 核心 | 存储前 PII 硬拦截网关（PIISafetyGateway）：按文本区间命中，Masking 模式只替换命中的字符（`[<规则>_REDACTED]`，API 密钥走 `redact_leaks`） | ✅ |
| `epoch_manager.py` | 核心 | 单调递增清除代次管理中枢（PurgeGenerationEpochManager） | ✅ |
| `extractor.py` | 门面 | 异步记忆提炼统一编排器（NoiseFreeAsyncMemoryExtractor） | ✅ |
| `__init__.py` | 导出 | 导出核心类与 DTO | ✅ |

## 依赖关系

- 依赖 Python 标准库、Pydantic 与 `core/security/detection`（隐私管线的检测器，检测口径单一来源）
- 被 `myrm-agent-server` 业务层作为底层无噪声记忆抽取与安全门禁引擎引用
