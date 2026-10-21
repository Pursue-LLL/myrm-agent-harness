# working_tree/

## Overview
Tree-structured working memory toolkit (ReTree implementation).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Tree-structured working memory toolkit (ReTree implementation). — EvidenceTree, EvidenceNode, FastContradictionDetector, TreeRepairEngine and models | — |
| `detector.py` | Core | Fast two-stage contradiction and temporal-update detector for evidence nodes. — FastContradictionDetector: 双阶段冲突与时态演化检测器（Stage 1 确定性预检 + Stage 2 Fast-LLM 语义仲裁） | ✅ |
| `engine.py` | Core | Tree repair and backtracking pruning engine. — TreeRepairEngine: 原子四步回溯修复、证据热替换、级联分支软剪枝与震荡阻尼引擎 | ✅ |
| `models.py` | Types | Evidence tree data models and typed containers for ReTree working memory. — EvidenceNodeStatus: 证据节点生命周期状态枚举; ConflictType: 语义冲突与时态演化分类枚举; EvidenceSource: 溯源信息容器（URL、Snippet、SHA-256指纹）; BoundedSummary: 严格有界摘要与核心实体指标容器 (+4 more) | ✅ |
| `tree.py` | Core | Topological Evidence Tree implementation for structured working memory. — EvidenceTree: 有向无环因果图容器，支持拓扑遍历、子树投影与 KV Cache 前缀时序装配 | ✅ |
