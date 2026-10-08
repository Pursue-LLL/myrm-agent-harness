# toolkits/memory/score_honesty 模块架构

## 架构概述

检索分数诚实性与双门禁透明检验引擎：严格物理拆分底层物理语义相似度（`raw_similarity`，[0, 1] 刚性区间）与多阶段排序综合分（`ranking_score`），提供白盒因子归因模型（`ScoreBreakdown`）和独立双门禁过滤器（`DualThresholdConfig`），彻底解决 RRF 与衰减排序导致的阈值腐烂和黑盒失真问题。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `models.py` | 核心 | 定义 `ScoreBreakdown`、`DualThresholdConfig`、`ThresholdEvaluationVerdict`、`HonestScoredCandidate`、`ScoreHonestyStats` 等强类型领域模型 | — |
| `pipeline.py` | 引擎 | `ScoreHonestyPipeline`：双门禁判定、白盒因子分解、降序保序排序与指标聚合 | — |
| `facade.py` | 门面 | `RetrievalScoreHonestySuite`：统一协调门面，提供 candidate 创建、评估、过滤和分歧诊断 | — |
| `__init__.py` | 入口 | 导出公共门面与数据模型 | — |

## 模块依赖

- 上游：`pydantic`
- 下游：`myrm-agent-server` 业务适配层、`MemorySearchResult` 检索契约
