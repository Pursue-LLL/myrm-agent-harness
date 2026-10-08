# PluggableContextHookPipelineAndMemoryInjectionSuite Architecture Contract

## 1. 模块定位与职责边界
- **定位**：属于 `myrm_agent_harness.toolkits.memory` 核心扩展套件，为前端自定义智能体提供全生命周期上下文拦截流水线与私有/共享双层记忆动态编织底座。
- **职责**：
  1. 全生命周期标准化 Hook 点位：涵盖 `BEFORE_AGENT_START`, `CONTEXT_TRANSFORM`, `AFTER_TOOL_CALL`, `BEFORE_LLM_REQUEST`；
  2. 双层记忆动态编织：支持前端自定义智能体的私有记忆（任务草稿、角色专属知识）与全局共享记忆（团队规范、通用偏好）按优先级有序编织，严格杜绝多智能体记忆串味；
  3. 洋葱模型流水线拦截：支持外部长期记忆与脱敏审查器以插件形式非侵入式挂载与热插拔；
  4. 性能与健壮性：轻量高效异步管线，单次拦截开销 < 0.5ms，内置超时与异常熔断隔离。
- **红线约束**：
  - 严禁包含 Web/HTTP 强依赖，纯 Python 异步领域模型设计；
  - 严禁使用 `Any` 类型，全面采用具体强类型注解；
  - 单文件行数原则上不超过 350 行。
