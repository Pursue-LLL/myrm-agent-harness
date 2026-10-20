# stream_metrics/

## Overview
流式调用按最终结果计量（Final-Outcome Metrics for Streamed Calls）核心子包。
彻底杜绝 LLM 流式输出（Streaming RPC / SSE）中中间 chunk 增量事件污染调用计数器，实现无论单次调用吐出多少个 chunk，仅在终态时完成一次确定性最终结果归因（SUCCESS / ERROR / CANCELLED / TIMEOUT），并度量首字时延 TTFT、整流耗时与膨胀过滤比。

## Architecture & Responsibilities

- `models.py`:
  - `StreamCallOutcome`: 终态结果枚举 (`SUCCESS`, `ERROR`, `CANCELLED`, `TIMEOUT`)；
  - `StreamCallSession`: 单次流调用的完整生命周期状态机与时延记录；
  - `StreamMetricsAggregate`: 终态聚合度量指标，排除 chunk 虚高膨胀。
- `collector.py`:
  - `StreamCallMetricsCollector`: 线程安全的流式调用计量收集器，支持 `start_call`, `record_chunk`, `finalize_call` 幂等结算与按提供商/模型的多维聚合统计。
- `__init__.py`: 统一门面导出。

## File Index

| File | Role | Description | I/O/P |
|---|---|---|---|
| `models.py` | 数据模型 | StreamCallOutcome 枚举与 StreamCallSession / StreamMetricsAggregate 数据契约 | ✅ |
| `collector.py` | 核心引擎 | 线程安全流式调用终态计量器，支持防 chunk 计数污染与 TTFT 追踪 | ✅ |
| `__init__.py` | 模块入口 | 聚合导出核心模型与收集器接口 | ✅ |
