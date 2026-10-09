# multi_session_workspace Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.multi_session_workspace`
核心职责：多会话并行网格工作区布局调度、启发式智能工程根目录自动嗅探与跨会话状态互通穿透总线套件。

## 模块结构
| 文件 | 职责 |
|---|---|
| `workspace_types.py` | 强类型契约、根特征分类、网格布局枚举、插槽角色与跨会话引用结构体 |
| `project_root_sniffer.py` | 启发式智能工程根目录嗅探器，结合 VCS、构建清单与 monorepo 指标及沙箱防逃逸 |
| `parallel_workspace_deck.py` | 多会话网格视口工作区调度器，管理 1x2、2x2 与 Tabbed 并行视口与聚焦状态 |
| `cross_session_reference_bus.py` | 跨会话状态穿透与引用总线，打破会话孤岛并生成受控提示词注入块 |
| `multi_session_workspace_suite.py` | 统一协调主门面 `MultiSessionParallelWorkspaceAndRootDiscoverySuite` |
| `__init__.py` | 包级公共符号门面导出 |
