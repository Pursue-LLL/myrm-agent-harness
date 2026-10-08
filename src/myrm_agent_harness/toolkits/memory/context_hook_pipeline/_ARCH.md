# PluggableContextHookPipelineAndMemoryInjectionSuite Architecture Contract

## 1. 模块定位与职责边界
- **定位**：属于 `myrm_agent_harness.toolkits.memory` 核心扩展套件，为前端自定义智能体提供全生命周期上下文拦截流水线与私有/共享双层记忆动态编织底座。
- **职责**：
  1. 全生命周期标准化 Hook 点位：涵盖 `BEFORE_AGENT_START`, `CONTEXT_TRANSFORM`, `AFTER_TOOL_CALL`, `BEFORE_LLM_REQUEST`；
  2. 双层记忆动态编织：支持前端自定义智能体的私有记忆（任务草稿、角色专属知识）与全局共享记忆（团队规范、通用偏好）按优先级有序编织，严格杜绝多智能体记忆串味；
  3. 洋葱模型流水线拦截：支持外部长期记忆与脱敏审查器以插件形式非侵入式挂载与热插拔；
  4. 执行遥测与失败阻断：同步管线，每个 hook 产出 `HookExecutionReport`（耗时、是否修改、是否阻断）；hook 抛出异常即以失败原因阻断信封并终止当前阶段。
- **红线约束**：
  - 严禁包含 Web/HTTP 强依赖，纯 Python 领域模型设计；
  - 严禁使用 `Any` 类型，全面采用具体强类型注解；
  - 单文件行数原则上不超过 350 行。

## 2. 文件清单

| 文件 | 地位 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 核心 | 生命周期阶段与优先级枚举、记忆片段与双层载荷、可变上下文信封、Hook 执行报告 | ✅ |
| `pipeline.py` | 核心 | `PluggableContextHookPipeline`：按阶段注册 hook（同 id 覆盖），按优先级升序同步执行并返回逐 hook 报告；hook 阻断或抛异常即终止当前阶段 | ✅ |
| `dual_layer_weaver.py` | 核心 | `DualLayerMemoryWeaver`：过滤他人私有片段，在 token 预算内私有优先、共享补足，生成注入用 Markdown 块 | ✅ |
| `facade.py` | 门面 | `ContextHookPipelineSuite`：hook 注册、阶段执行、记忆编织与注入、完整生命周期编排及按阶段计数 | ✅ |
| `__init__.py` | 门面 | 导出门面、钩子链、编织器与数据模型 | ✅ |

## 3. 依赖关系

- 仅依赖 `pydantic` 与标准库；包内依赖方向为 `models` ← `pipeline` / `dual_layer_weaver` ← `facade`。
- 经 `myrm_agent_harness.toolkits.memory` 重新导出，被 `myrm-agent-server/app/services/memory/context_hooks/` 消费。
