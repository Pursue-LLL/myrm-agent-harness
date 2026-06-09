# toolkits/deploy 模块架构

---

## 架构概述

Agent 级 artifact 部署工具包。定义 `DeployBackend` Protocol 和 `create_deploy_tool()` 工厂，让 Agent 能通过对话触发部署。框架层仅定义契约，不依赖任何具体托管平台。

---

## 文件清单

| 文件 | 地位 | 职责 |
|------|------|------|
| `__init__.py` | 入口 | 导出 `DeployBackend`、`create_deploy_tool` |
| `deploy_agent_tools.py` | ✅ 核心 | `DeployBackend` Protocol + `DeployResult` 数据类 + `create_deploy_tool()` 工厂 |

---

## 设计要点

- **Protocol 边界**：`DeployBackend` 定义 `preflight()`、`execute_deploy()`、`get_artifact_name()` 三个方法，业务层实现。
- **HITL 审批**：使用 LangGraph `interrupt` 暂停执行，等待用户确认后再部署（与 `ask_question_tool` 相同模式）。
- **Deferred 加载**：工具放入 `deferred_tools`，仅在 Agent 首次需要时激活，不增加常规对话的工具选择负担。

---

## 依赖关系

- `langchain_core.tools`：`BaseTool`、`@tool` 装饰器
- `langgraph.types`：`interrupt`（HITL 审批）
- 业务层实现：`myrm-agent-server/app/services/deploy/agent_deploy_service.py`
