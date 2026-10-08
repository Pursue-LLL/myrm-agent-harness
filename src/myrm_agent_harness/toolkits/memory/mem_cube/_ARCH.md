# mem_cube/

## 架构概述

Memory Cube 空间治理与读写分离动态挂载套件（Memory Cube Scoped Isolation & Dynamic Mounting Suite · Item 124 P0 · 对标 MemOS `mem_cube` 核心实证与空间隔离架构）。

### 核心机制
1. **一等公民 Memory Cube 空间抽象（First-Class Memory Cube Abstraction）**：
   - 终结扁平散乱的字符串 scope 传参，将记忆划分为独立的 Cube 空间容器：
     - `GLOBAL_SHARED`: 全局跨智能体共享常识、通用用户偏好与开发标准；
     - `PROJECT_WORKSPACE`: 具体工程/代码仓库的领域知识与架构上下文；
     - `AGENT_PRIVATE`: 专属于特定智能体的私有经验、个人偏好与草稿轨迹；
     - `EPHEMERAL_TASK`: 临时子任务或单次会话的生命周期沙盒空间。
2. **读写分离与多 Cube 动态挂载（Decoupled Read/Write Mounting）**：
   - 检索时支持声明 `readable_cube_ids`（例如多 Agent 协同召回：[全局通用偏好 Cube + 项目规范 Cube + 架构师专有经验 Cube] 联合检索召回）；
   - 写回时支持声明 `writable_cube_ids`，严格定向写入当前智能体私有 Cube 或工作区 Cube，杜绝越权污染只读 Cube。
3. **隔离越权硬门禁与联合检索（Federated Query & RBAC Guardrail）**：
   - 默认启用 `strict_isolation` 策略，任何尝试向非授权只读 Cube 发起写操作的请求将被硬拦截，确保知识库资产纯净性。

## 文件清单

| 文件 | 角色 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 实体模型 | 定义 CubeScopeType, MemoryCube, CubeMemoryRecord, MountPolicy, CubeQueryRequest, CubeQueryResult, CubeWriteRequest, CubeWriteResult | ✅ |
| `cube_store.py` | 存储引擎 | 线程安全维护 MemoryCube 命名空间隔离、按 Cube 存取与记录查询 | ✅ |
| `mount_router.py` | 路由调度 | 负责读写权限校验、读写分离拓扑路由与跨 Cube 联合检索分发 | ✅ |
| `orchestrator.py` | 调度门面 | 聚合 Cube 生命周期管理、多智能体挂载策略绑定与统一操作门面 | ✅ |
| `__init__.py` | 包门面 | 统一导出核心类、数据模型与路由实体 | — |

## 依赖关系

- 依赖标准库与 `pydantic`
- 被 `myrm-agent-server/app/services/memory/` 业务层消费
