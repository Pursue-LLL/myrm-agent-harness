# noise_free_extractor/

## 架构概述

工具回执噪声剥离式异步记忆提炼、PII 正则清洗网关与单调递增清除代次套件 (Item 88, P0)。
汲取 Anthropic Commerce Agents (`commerce_common/memory.py`) 记忆隔离与 `purge_generation` 设计，彻底解决三大痛点：
1. **工具噪声污染**：`ToolNoiseFilter` 物理剥离 tool_call、tool_result 与营销 JSON 代码块，确保提取器仅分析自然语言对话；
2. **PII 与合规泄漏**：`PIISafetyGateway` 正则硬拦截信用卡（Luhn 验证）、IBAN、身份证、敏感密钥等，提供 Reject 与 Masking 模式；
3. **幽灵记忆死灰复燃**：`PurgeGenerationEpochManager` 维护用户级单调递增 `purge_generation`，后台异步写回时核验代次，过期自动丢弃。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `types.py` | 实体 | 纯净对话消息、PII 违规详情、代次状态与候选事实 DTO | ✅ |
| `noise_filter.py` | 核心 | 工具回执物理剥离预处理器（ToolNoiseFilter） | ✅ |
| `pii_gateway.py` | 核心 | 代码级 PII 正则前置拦截网关（PIISafetyGateway） | ✅ |
| `epoch_manager.py` | 核心 | 单调递增清除代次管理中枢（PurgeGenerationEpochManager） | ✅ |
| `extractor.py` | 门面 | 异步记忆提炼统一编排器（NoiseFreeAsyncMemoryExtractor） | ✅ |
| `__init__.py` | 导出 | 导出核心类与 DTO | ✅ |

## 依赖关系

- 仅依赖 Python 标准库与 Pydantic
- 被 `myrm-agent-server` 业务层作为底层无噪声记忆抽取与安全门禁引擎引用
