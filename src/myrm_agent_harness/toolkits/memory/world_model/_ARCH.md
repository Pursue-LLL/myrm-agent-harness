# L3 World Model Architecture

## 1. 模块定位
`src/myrm_agent_harness/toolkits/memory/world_model` 属于 Harness 框架核心记忆套件层，负责抽象维护超越单条细碎 Memory 的宏观世界模型实体。

## 2. 核心职责
- **四维宏观实体抽象**：通用安全与工程规则（`general_rules`）、运行时环境基准（`project_environment`）、架构契约与拓扑（`project_contract`）、核心领域常识（`domain_knowledge`）。
- **状态持久与版本演进**：通过 `L3WorldModelRecord` 提供带乐观锁版本（`version`）的原子状态维护。
- **环境基准集成**：将多运行时环境快照（`ProjectEnvironmentSnapshot`）格式化并无缝并入宏观世界模型。
- **宏观上下文紧凑序列化**：通过 `render_macro_context` 输出开箱即用的 Markdown 注入块，以不可撤销的防伪边界（`<!-- L3_WORLD_MODEL_BEGIN -->`）包裹。

## 3. 设计原则
- **严格零 Any**：所有数据模型均采用不可变 Dataclass 与强类型枚举。
- **纯粹框架定位**：不包含单租户业务判定与工作区文件解析逻辑（文件解析由 Server 层探针提供），确保跨平台通用。
