# todo_store/

## 架构概述

共享 Todo 计划声明存储与控制字符安全清洗 HUD 只读投影子系统（Shared Todo Store & Terminal-Escape Safe HUD Reader）。

### 核心设计原则

1. **计划声明 vs 执行凭证边界 (Plan Declaration Semantic Boundary)**：
   明确声明「Todo items are plan declarations, not execution evidence」强契约。计划项仅供跨智能体或跨插件对齐预期目标，绝不可替代真实工具调用执行证据或验证回执。
2. **轻量容量硬顶约束 (Strict Capacity & Length Bounds)**：
   - 最大条目上限：`MAX_TODO_ITEMS = 20`；
   - 标题字符上限：`MAX_TITLE_LENGTH = 80`；
   - 描述字符上限：`MAX_DESCRIPTION_LENGTH = 200`；
   防止恶意提示词膨胀或失控递归写入。
3. **读写双向控制字符安全清洗 (Bidirectional C0/C1 Stripping)**：
   在写入存储（`write` / `save`）与读取投射（`read` / `project_hud`）的双重边界，严格剥离全量 C0 控制字符（`\x00-\x1F`、`\x7F`）、C1 控制字符（`\x80-\x9F`）以及 ANSI CSI / OSC 转义序列，坚决杜绝提示词转义欺骗与 TUI / HUD 视图破坏。

---

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `__init__.py` | 门面 | 导出门面类 `SharedTodoStore`、`SharedTodoHudReader`、数据契约与标准 Agent 元工具 | ✅ |
| `types.py` | 契约 | 定义 TodoItem 状态机枚举、`TodoItem`、`TodoStoreState`、`TodoHudProjection` 与核心语义说明常量 | ✅ |
| `sanitizer.py` | 安全 | 纯函数实现双向 C0/C1 控制字符与 ANSI 转义序列剥离清洗（`strip_control_characters`、`sanitize_todo_text`） | ✅ |
| `store.py` | 核心 | 线程安全、支持跨进程文件原子写入的计划存储实体（容量门禁、状态机流转、增删改查） | ✅ |
| `hud_reader.py` | 核心 | 只读轻量 HUD 投影生成器：计算完成率、提取当前活跃计划项并渲染安全单行终端文本 | ✅ |
| `tools.py` | 工具 | LangChain 标准 Agent 元工具：`manage_todo_plan` 与 `read_todo_hud` | ✅ |

---

## 依赖关系

- **上级目录**：`myrm_agent_harness.agent.sub_agents`
- **被依赖方**：`myrm-agent-server` 业务层 Todo 服务与多智能体编排工作流
