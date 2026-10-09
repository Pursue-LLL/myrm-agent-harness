# lookback_aligned_prune Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.lookback_aligned_prune`
核心职责：Prompt Cache 回看块位对齐剪枝下限套件，根据 Provider 实际发射块位与保留安全裕度计算下限，杜绝误删缓存回看窗口内的工具结果而引发高昂前缀失效重算。

## 模块结构
| 文件 | 职责 |
|---|---|
| `lookback_prune_types.py` | 强类型契约、Provider 缓存分类、内容块种类、回看下限结果、剪枝决策与配置模型 |
| `provider_block_projector.py` | 消息至 Provider 发射 Content Block 精确投影器，还原 tool_use、image 与 file_ref 真实块位占用 |
| `lookback_floor_calculator.py` | Provider 回看块位下限计算器，结合 20 块位上限与 6 预留 headroom 计算保护边界 |
| `lookback_aligned_pruner.py` | 尊重回看下限的工具输出剪枝保护器，禁止剪改受保护窗口内的任何工具输出 |
| `lookback_aligned_prune_suite.py` | 统一协调主门面 `PromptCacheLookbackPositionAlignedPruneFloorSuite` |
| `__init__.py` | 包级公共符号门面导出 |
