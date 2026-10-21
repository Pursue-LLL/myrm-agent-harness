# Hierarchical Leader-Worker Debate & Synthesis Pattern Architecture

## 概述
提供开箱即用的分层决策咨询工作流模板（Hierarchical 3-Stage Leader-Worker Debate & Synthesis Pattern）。对标字节跳动扣子桌面端实测的「Leader 拆解分派 + 调研专员探索 + 可行性审计专员评估 + 最终决策权衡收敛矩阵（Trade-off Matrix）」全套多智能体编排范式。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 入口 | 统一公共导出门面。 | ✅ |
| `types.py` | 核心 | 定义工作流阶段（`SynthesisPhase`）、专员角色（`SynthesisRole`：`leader_coordinator`、`research_analyst`、`feasibility_auditor`）、对比维度（`TradeoffDimension`）、候选提案（`CandidateProposal`）、权衡对比矩阵（`TradeoffMatrix`）与会话状态（`SynthesisWorkflowState`）。 | ✅ |
| `engine.py` | 核心 | `HierarchicalDebateSynthesisEngine`，实现三段式预设的装配、Leader 自动子任务 DAG 分解与依赖拓扑注入、专员提案提交、多轮交叉辩论收敛保护、以及多维度权衡对比矩阵加权综合评分与胜出推荐算法。 | ✅ |
