# sufficiency/ 模块架构

## 架构概述

Retrieval Sufficiency Guard (RSG)：检索后 LLM 评估结果是否充分覆盖查询，含负面约束检测；不足时引导 re-search。详见 [RETRIEVER_SYSTEM.md](../RETRIEVER_SYSTEM.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | 核心 | 公开 API：`evaluate_sufficiency`、`SufficiencyVerdict`、`SufficiencyConfig` | ✅ |
| `types.py` | 核心 | `SufficiencyVerdict`、`SufficiencyConfig` 数据类型 | ✅ |
| `evaluator.py` | 核心 | `evaluate_sufficiency()` — 轻量 LLM 充分性判定。模型装配 temperature 语义：顶层 `cfg.temperature` 优先 → `model_kwargs.temperature` 其次 → 默认 0.0 兜底（保证评估确定性），避免具名参数冲突 | ✅ |
| `prompts.py` | 辅助 | 评估 prompt 模板 | ✅ |

## 模块依赖

- `toolkits/llms/` — 轻量 LLM 实例
- `utils/json_parsing/` — `parse_llm_json_object` 容错解析 LLM 判定输出（fence/prose/裸控制字符/尾逗号）
- 调用方：`toolkits/retriever/` 混合检索管线（条件激活）
