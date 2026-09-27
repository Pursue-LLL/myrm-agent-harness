# Time-Traveling Stream Rules (TTSR) Zero-Tax Engine

## 架构概述

提供流式生成中实时零 Token 税规则匹配、毫秒级原位中断、违规片段丢弃、带 `WorkingMemoryMark.TRAP_SHIELD` 纠偏注入与 Compaction 压缩永存能力。

## 文件清单

| 文件 | 地位 | 职责 |
| --- | --- | --- |
| `__init__.py` | 入口 | 模块公共接口与类导出 |
| `types.py` | 核心 | 强类型规则定义（`StreamRule`）、匹配结果（`TtsrMatchResult`）及目标与行为声明 |
| `matcher.py` | 核心 | 128 字符滑动窗口正则匹配器（`TtsrMatcher`）与流式 JSON 解转义器（`PartialJsonUnescaper`） |
| `coordinator.py` | 核心 | TTSR 规则生命周期协调器（`TtsrCoordinator`：冷却期控制、有界重试熔断与纠偏消息生成） |
