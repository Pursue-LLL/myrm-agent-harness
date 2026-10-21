# reasoning_semantics/

## 架构概述

推理 Token 计费语义契约、按提供方归一化与重复计数回归守卫套件。
针对不同提供商（OpenAI、Anthropic、DeepSeek 等）在 reasoning/thinking tokens 统计口径上的分歧，明确建立不变量契约（`total_tokens == prompt_tokens + completion_tokens` 且 `reasoning_tokens ⊆ completion_tokens`），统一提供方策略适配映射，严防上游将推理 Token 进行二次累加导致的重复计数、成本双重计算与预算提前误熔断。

上级架构：[../_ARCH.md](../_ARCH.md)。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 模块门面导出 | ✅ |
| `models.py` | 数据契约 | `ReasoningInclusionPolicy`、`NormalizedTokenUsageSnapshot`、`InvariantCheckResult` 等不可变契约定义 | ✅ |
| `normalizer.py` | 归一化引擎 | `ProviderReasoningNormalizer`：按提供方收敛口径策略，自动解析不同厂商响应结构并统一消除重复计数 | ✅ |
| `invariant_guard.py` | 不变量守卫 | `ReasoningInvariantGuard`：运行时轻量验证器，侦测总量二次累加与推理溢出违规，并支持就地自愈修正 | ✅ |
