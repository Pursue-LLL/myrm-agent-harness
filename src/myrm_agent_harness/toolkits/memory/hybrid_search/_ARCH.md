# Dual-Engine Hybrid Search & Graceful Fallback Suite Architecture

## 1. 模块定位与职责边界 (Boundary & Scope)
- **定位**：属于 Harness 框架内嵌的无外部网络依赖高可用检索核心，服务于单机/沙箱内的 Agent 记忆系统。
- **职责**：
  1. 并发调度 SQLite FTS5 关键词检索与高维向量相似度检索；
  2. 提供三态自愈断路器（AdaptiveCircuitBreaker），在向量 Provider 超时或报错时实现 <1ms 平滑降级为纯 FTS5 检索；
  3. 执行四合一确定性数学重排：`BM25 Score + Vector Cosine + Recency Decay (30d Half-Life) + Importance Multiplier + Exact Phrase Boost`；
  4. 基于 Token Jaccard 的轻量级 MMR 多样性去重与 Token 预算安全截断。
- **严禁事项**：
  - 禁止在框架层硬编码具体外部云端大模型 API 或鉴权密钥（这些属于 Server 业务层装配工作）；
  - 禁止引入多租户逻辑，框架专注于单机/单沙箱的高性能检索。

## 2. 核心架构拓扑 (Component Topology)
- `models.py`：数据契约模型（`SearchMode`, `FallbackReason`, `CircuitState`, `HybridSearchHit`, `HybridSearchQuery`, `HybridSearchReport`）；
- `circuit_breaker.py`：纯内存三态状态机，自动跟踪连续故障并在冷却期后通过试探调用自愈；
- `ranker.py`：词法清洗与防崩溃、BM25 单调归一化、时间半衰期衰减、MMR 多样性与 Token 截断；
- `engine.py`：双路并行编排引擎，集成硬超时强杀、自适应降级阈值与诊断遥测。

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for dual engine hybrid search. | ✅ |
| `circuit_breaker.py` | Core | Pure in-memory tri-state adaptive circuit breaker. | ✅ |
| `engine.py` | Core | Dual-engine hybrid search orchestrator. | ✅ |
| `models.py` | Types | Data contracts and report models for hybrid search. | ✅ |
| `ranker.py` | Core | Lexical sanitization, recency decay, and MMR reranker. | ✅ |

