# Turn Billed Usage Dual Count Architecture

## Overview
本子包实现回合级 Billed Usage 双计数核心架构（`TurnBilledUsageDualCount`），解决多轮对话与单轮内多次调用（re-drive / tool loops）场景下真实成本账单累加与前缀缓存冻结决策（Freeze Decision）混淆的痛点。

## Core Invariants
1. **真实账单（The Bill · `summed_with`）**：
   - 每次物理调用的 `input_tokens`、`output_tokens`、`cache_read`、`cache_write` 绝对累加，真实反映向 LLM 厂商支付的总消耗，支持多轮任务精准成本归因。
2. **冻结决策（The Freeze · `merged_with`）**：
   - 保留最新一次有效缓存调用的状态视图，绝不叠加多次调用的缓存量，防止虚假膨胀前缀缓存深度而误导滑窗与缓存冻结逻辑。
3. **自适应格式回写（`write_in_shape`）**：
   - 原位识别并重写 Anthropic 与 OpenAI 响应规范中的 usage 键名，保障上游网关和下游调用方透明无缝消费。

## File Layout
| 文件 | 类型 | 职责 | 状态 |
| :--- | :--- | :--- | :--- |
| `models.py` | 核心实现 | `NormalizedUsage`（双运算操作符 `summed_with` vs `merged_with`）与 `TurnUsageTracker` 生命周期追踪器 | ✅ |
| `__init__.py` | 门面导出 | 聚合导出模块内所有模型与追踪器类 | ✅ |
| `_ARCH.md` | 架构文档 | 模块定位、核心不变量与文件表 | ✅ |
