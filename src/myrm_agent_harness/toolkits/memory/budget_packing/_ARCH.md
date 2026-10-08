# budget_packing/

## 架构概述

预算贪心边际价值召回装箱套件（Budget Greedy Marginal Value Recall Packing Suite · Item 122 P2 · 对标 FrankHu-HK/mnemosyne `brain.py:548` `_budget_recall` 贪心背包算法）。

### 核心机制
1. **边际价值与价值密度评估（Marginal Value Density）**：
   - 基础价值：$U(c) = \text{relevance\_score} \times \text{confidence\_score}$；
   - 边际信息增益（MIG）：计算候选片段与已选片段集之间的词袋/n-gram 重叠度 $\text{redundancy}$，经多样性惩罚因子 $\lambda$ 衰减：$\text{MIG} = \max(0.0, 1.0 - \lambda \times \text{redundancy})$；
   - 边际价值：$\text{MV} = U(c) \times \text{MIG}$；
   - 价值密度：$\text{MVD} = \frac{\text{MV}}{\max(1, \text{billed\_tokens})}$。
2. **贪心背包迭代装箱与回填（Greedy Knapsack Packing & Backfill）**：
   - 优先装入边际价值密度最高的候选记忆片段；
   - 支持贪心背包回填（Greedy Backfill），当高位大片段超出预算时，自适应回填体积较小且边际价值合规的次优候选，最大化 Token 预算利用率；
   - 抑制语义重复（Redundancy Suppressed）与低于门槛的低质碎片。
3. **双轨 Token 计量与成本审计（Dual-Track Token Accounting）**：
   - 区分真正进入模型 Prompt 产生账单的 **计费 Token（Billed Tokens）** 与本地存储、索引开销的 **存储 Token（Storage Tokens）**；
   - 输出详细的预算填满率、冗余 Token 拦截量与存储 Token 节省率体检报告。

## 文件清单

| 文件 | 角色 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 实体模型 | 定义 RecallCandidate, BilledTokenBudget, MarginalValueMetrics, PackedCandidateItem, TokenAccountingReport, PackedRecallResult | ✅ |
| `marginal_value_evaluator.py` | 评估引擎 | 计算片段间 Jaccard/n-gram 语义重叠度、多样性衰减与边际价值密度 | ✅ |
| `greedy_packer.py` | 装箱核心 | 贪心背包装箱算法实现，执行动态排序、容量判定、回填优化与双轨计量 | ✅ |
| `orchestrator.py` | 调度门面 | 装箱门面调度器，支持贪心装箱模式与传统 limit 模式对比及单步诊断 | ✅ |
| `__init__.py` | 包门面 | 统一导出核心类、数据模型与工具函数 | — |

## 依赖关系

- 依赖内部基础模块：`dataclasses`, `enum`, `typing`, `re`
- 被 `myrm-agent-server/app/services/memory/` 消费
