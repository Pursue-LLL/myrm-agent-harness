# Conclusion Attribution & Chat Evidence Architecture Contract

## 1. 架构动机与第一性原理 (Motivation & First Principles)

在长程 Agent 记忆管理中，传统的扁平事实记录丢失了因果推导脉络与原始证据链，导致两大核心痛点：
1. **黑盒事实腐败与不可审计**：审计人员无法判断一条结论是用户显式指令（Explicit）还是 Agent 自主发散归纳（Inductive），当结论发生漂移或幻觉时无法溯源原始支撑证据（Message Evidence）。
2. **级联失效与死锁逻辑环**：当某条前提事实被纠正或删除时，由于缺乏前驱/后继因果引用，无法得知下游哪些衍生结论已被证伪，容易在反思循环中产生 A 衍生 B、B 又强化 A 的虚假闭环逻辑环。

## 2. 核心架构裁决 (Core Architectural Decisions)

本套件遵循 Honcho 3.2.0 实践并结合 Myrm 单机沙箱架构深度演进：
1. **多级显式归因数据结构 (Attribution Schema)**：
   - 每条结论携带 `level`（`EXPLICIT`, `DEDUCTIVE`, `INDUCTIVE`, `ABDUCTIVE`, `CONTRADICTION`）；
   - `source_ids`：记录直接前提结论 ID 列表，构筑严格有向无环推导图（DAG）；
   - `times_derived`：独立复现派生计数器，量化知识稳固度；
   - `evidence_message_ids`：直连支撑该事实的原始会话消息标识符。
2. **因果推导图与防幻觉环治理 (Derivation Graph & Cycle Prevention)**：
   - `ConclusionDerivationGraphEngine` 在注册阶段执行严格的 DFS/Tarjan 环检测，遇到循环推导直接拦截并抛出 `DerivationCycleError`；
   - 支持双向树遍历（向上查找由我衍生了谁，向下查找我是由谁推导的），支持毫秒级级联失效影响面分析（Cascade Invalidation Analysis）。
3. **按需 Chat Evidence 模式 (On-Demand Evidence Mode)**：
   - 默认模式下 `include_evidence=False`，仅返回语义精简回答，零额外 Token 膨胀，确保 Prompt Cache 命中率 100%；
   - 显式请求时打包返回强类型 `ChatEvidenceBundle`（包含命中的结论、原始会话片段、工具调用痕迹），提供法律与工程级可解释性。

## 3. 分层与调用边界 (Layer Boundaries)

- **框架层 (`myrm_agent_harness.toolkits.memory.conclusion_evidence`)**：
  提供纯单机高吞吐的推导图引擎、环检测、证据打包与统一门面 `ConclusionEvidenceSuite`，无多租户包袱；
- **业务层 (`myrm_agent_server.services.memory.conclusion_evidence`)**：
  严格通过 Harness 顶级门面导入（100% 守住 0 deep import 门禁），暴露 REST API 路由。

## 4. 文件清单 (File Index)

| 文件 | 角色 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出归因模型、推导图引擎、证据服务与统一套件 | ✅ |
| `models.py` | 类型 | 显式归因类型、派生计数器、证据绑定与评估模型 | ✅ |
| `derivation_graph.py` | 核心 | 因果推导有向无环图引擎、循环检测与级联失效分析 | ✅ |
| `evidence_service.py` | 核心 | 会话证据提取、按需打包与高保真追溯服务 | ✅ |
| `facade.py` | 门面 | 结论归因与证据链统一套件门面 | ✅ |
