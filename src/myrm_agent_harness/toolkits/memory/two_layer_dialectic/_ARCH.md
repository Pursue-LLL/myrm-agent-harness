# two_layer_dialectic/

## 架构概述

两层上下文解耦与多遍辩证推理调和套件（Two-Layer Context Injection & Multi-Pass Dialectic Reconciliation Suite · 对标 Hermes Agent + Honcho 官方实践）。

### 核心机制
1. **Layer 1: Base Context 极简低频基础层**：
   由 Session Summary 与 Peer Card 构成，依据 `context_cadence` 低频刷新。挂载于 User Message 尾部，保持 System Prompt 绝对冻结，100% 保护 KV Cache。
2. **Layer 2: Dialectic Reasoning 辩证推理调和层**：
   在检测到历史记忆与当前指令冲突时，触发深浅可控的 1~3 遍辩证推理循环（Pass 0 审查 -> Pass 1 针对性综合 -> Pass 2 矛盾调和），直接在推理层自愈冲突。
3. **三大正交调优旋钮**：
   - `context_cadence`：基础上下文刷新间隔轮次；
   - `dialectic_cadence`：辩证推理触发间隔轮次；
   - `dialectic_depth`：辩证推理深度（1~3 遍）；
   - `dialectic_reasoning_level`：算力等级（fast/standard/deep）。

## 文件清单

| 文件 | 角色 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 实体模型 | 定义 BaseContextBundle, ConflictItem, DialecticCadenceConfig, DialecticPassRecord, DialecticReconciliationResult | ✅ |
| `base_context_engine.py` | 核心引擎 | Layer 1 基础上下文生成、缓存与 User Message 尾部注入，保护 System Prompt KV Cache | ✅ |
| `dialectic_engine.py` | 核心引擎 | Layer 2 冲突检测与自适应 1~3 遍辩证推理调和，生成行动共识指令 | ✅ |
| `injector.py` | 上下文注入 | 两层上下文动态注入组装器，负责 XML 格式化与 Prompt Cache 保活尾部挂载 | ✅ |
| `reconciler.py` | 推理调和 | 多遍辩证推理调和引擎，执行审查、综合与调和消除认知矛盾 | ✅ |
| `orchestrator.py` | 调度门面 | 两层调度协调器，负责正交旋钮控制与全链路输入组装 | ✅ |
| `__init__.py` | 包门面 | 统一导出核心引擎与模型 | — |
