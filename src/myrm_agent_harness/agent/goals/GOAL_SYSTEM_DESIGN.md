# Goal System Design

## 架构概述
Goal System 负责管理长期任务（Long-running Tasks）的生命周期、预算控制、目标规划和进度追踪。
它将传统的"闭眼裸奔"的 Agent 执行模式，升级为"带图纸的工程流水线"。

## 核心组件

### 1. GoalManager (状态机与预算)
- 负责 Goal 的创建、状态流转（ACTIVE, PAUSED, PENDING_APPROVAL, BUDGET_LIMITED, COMPLETE, CANCELLED, NEEDS_HUMAN_REVIEW）。
- 四维预算控制（tokens / USD / wall-clock time / turns），任何一维耗尽即自动转为 BUDGET_LIMITED。
- **自适应循环与收敛控制**：GoalBudget 扩展 `convergence_window`（连续无进展轮次阈值）、`loop_on_pause`（暂停后自动重启）、`max_loop_restarts`（重启安全上限）三个可选字段。Goal 运行时追踪 `no_progress_streak`（连续零工具调用计数）和 `loop_restarts`（已重启次数）。
- `resume_goal(reset_turns=True)` 方法支持恢复暂停或预算受限的 Goal，重置 convergence 计数器（no_progress_streak、loop_restarts）并可选重置 turn 计数。
- `account_usage(turn_delta=1)` 在每个 continuation turn 精确递增 turns_used。
- **Goal Lifecycle Metrics**：在 `create_goal`、`update_status`（终态）、`resume_goal` 三个状态转换点自动记录 Prometheus 指标（6 counters + 3 histograms），通过 `observability/metrics/goal_metrics.py` 定义，为 SaaS 运营监控提供 goal 完成率、预算耗尽率、耗时分布、Token/Cost 分布等关键数据。
- **多分支上下文隔离与迁移 (Branch-Aware Stash & Migrate)**：
  - `stash_goal` 和 `restore_goal` 实现基于 `session_id` + `branch_name` 的联合主键隔离，彻底解决多工作区/多会话并发数据覆盖 Bug。
  - Server 层配合 `watchdog` 零延迟监听 `.git/HEAD`，实现**意图感知的目标迁移**：当检测到新建分支（如 `checkout -b`）时，自动将当前 Active Goal 继承（MIGRATE）到新分支；当切回老分支时，自动挂起并恢复（STASH/RESTORE）对应上下文，完美契合真实 Git 工作流。
- **运行时动态子目标 (Dynamic Runtime Subgoals)**：
  - 支持在任务执行过程中，随时通过 `/subgoal` 指令追加新的验收标准或子任务。
  - 最新的 Subgoal 具备**绝对优先级**，被无损注入到 `Semantic Judge` 和 `Continuation Prompt` 中，确保 Agent 能够灵活响应临时变更的需求，极大增强了长任务场景下的动态干预能力。
- **Objective Hot-Edit (运行时目标热编辑)**：
  - `update_objective(goal_id, new_objective)` 允许在 Goal 执行期间修改目标文本而不丢失进度、Token 统计、learnings 等上下文。
  - 通过 `SteeringToken.steer()` 注入 `build_objective_updated_steering_message()` 构建的引导消息，消息中：
    - 新目标使用 `<untrusted_objective>` 标签防 prompt 注入。
    - 附带当前预算状态（tokens used / remaining），帮助 Agent 评估剩余资源。
    - 指导 Agent 调整方向、更新已有 Plan、遵守 active constraints。
  - `continuation.py` 的 `has_pending` 检查确保 steering 消息在 turn 边界注入，不破坏工具链执行。

### 2. Goal Interceptor (前置规划与物理挂起)
- 在主 Agent 循环启动前，拦截 `/goal` 请求。
- 如果当前 Goal 还没有计划（Plan），则调用 `PlannerAgent` 自动生成一份结构化的 JSON 计划（包含阶段、验收标准、依赖关系）。
- **核心机制**：生成计划后，将 Goal 状态置为 `PENDING_APPROVAL`，并触发 `langgraph.types.interrupt()` 强行物理挂起当前 Agent 执行流。将控制权 100% 交还给用户。

### 3. CompletionGuard (基于客观证据的严格完工护栏)
- 在 Agent 试图输出最终答案（结束任务）时，拦截请求。
- **强制计划校验**：读取当前 Plan，如果发现还有未完成（`status != "completed"`）的步骤，直接阻断完工请求。
- **强制物理证据校验 (TDD-like) 与智能模态感知**：分析 Agent 的历史工具调用记录（CallRecords）。
  - **代码任务严防死守**：如果发现 Agent 修改了代码文件（如 `.py`, `.js` 等）但没有运行任何测试/验证命令（如 `pytest`, `python script.py` 等），或者运行了但报错了，护栏将拦截完工请求，并抛出 Tool Error 逼迫 Agent 去沙箱里跑测试并修复问题。
  - **前端视觉验证提醒**：如果修改了前端渲染文件（`.tsx/.jsx/.vue/.svelte/.astro/.css/.scss/.less/.html`，通过路径片段匹配智能排除 test/store/utils/hooks/types 等非渲染目录及 `.test.`/`.spec.`/`.config.`/`.stories.` 等非渲染文件）且未使用浏览器工具验证，追加 WARNING 提示 Agent 进行视觉确认。
  - **文本任务包容放行**：如果修改的仅仅是文本文件（如 `.md`, `.txt`），则只给出普通警告，允许正常完工，避免非代码任务陷入死循环。
- **优雅降级 (Graceful Degradation)**：当连续拦截次数达到 `max_rejections`（默认 3 次）时，不再粗暴地触发 `interrupt()` 导致前端假死，而是注入一个带有 `force_fail=True` 的特殊指令。该指令允许 Agent 完工，但**强制要求 Agent 在最终回复中向用户输出明确的 Markdown 警告**，说明其未能成功验证代码，请用户人工审查。
- 物理层面彻底杜绝了 AI 的"幻觉式完工"和"偷懒早退"，同时保证了系统的健壮性和用户体验。

### 4. PlannerMiddleware (静态蓝图与动态防漂移注入)
- **静态蓝图注入（零缓存损耗）**：负责将 Plan 的**静态结构**（目标、推理、各个阶段的描述和预期输出）注入到主 Agent 的 System Prompt 中，绝对不注入动态的完成状态，确保大模型的 Prefix Cache 100% 命中。
- **瞬态动态防漂移提醒**：为了对抗长上下文中的"近因效应（Recency Bias）"，在每次发给大模型的 `messages` 列表**末尾**（即最后一个 `HumanMessage` 中）动态追加当前阶段的焦点提醒，防止任务漂移。
- **决策快照系统 (Decision Log)**：在长任务中，为了防止上下文压缩（Compaction）导致 Agent 遗忘早期的架构决策，Middleware 会提取 Planner 记录的 `key_findings`，并将其作为瞬态指令一并注入到末尾。这保证了 Agent 永远不会丢失决策背景。

### 5. Continuation Guard Chain (自主续航判断)
- Guard chain 决定 Goal 是否应自动继续到下一轮：
  1. GoalProvider 存在？
  2. 有 ACTIVE Goal？
  3. 用户取消？
  4. Steering 消息待处理？
  5. 预算耗尽？（含 turns 维度）→ 首次触发时注入 wrap-up prompt 执行一轮总结（graceful conclusion），第二次直接终止。
  6. **收敛/循环/抑制**（三级判定）：
     - 6a. **Convergence**：当 `convergence_window` 已设置且 `no_progress_streak >= K` 时，标记 COMPLETE(convergence)。解决开放式目标以 BUDGET_LIMITED 结束的 UX 痛点，同时节省 token。
     - 6b. **Loop Restart**：当 `loop_on_pause=True` 且未超过 `max_loop_restarts` 时，触发 `trigger_goal_stream` 以新 context 立即重启，而非等待 Cron 分钟级延迟。
     - 6c. **Standard Suppression**：连续零工具调用 → PAUSED 防空转（原有行为）。
  7. **语义完成判断**（Semantic Judge）：使用廉价 LLM 判断目标是否已语义完成。当判定未完成时，Judge 的 reason 会被传递到下一轮的 continuation prompt 中（"Previous evaluation feedback" 块），使 Agent 知道具体缺口并针对性修复。
- **Budget Wrap-up Turn（预算耗尽优雅收尾）**：当预算首次耗尽时，不立即终止 Agent，而是注入 `build_wrapup_prompt`（"停止新工作，总结进度/剩余工作/下步建议"）触发额外一轮无工具的 LLM 调用，让 Agent 生成语义化总结作为 AssistantMessage 出现在聊天流中。通过 `_WRAPUP_SENTINEL` 标记检测防止无限循环，第二次进入 BUDGET_LIMITED 时直接终止。灵感来源：Codex `budget_limit.md` + Hermes `_handle_max_iterations`。
- 返回结构化 `ContinuationDecision`（verdict / reason / turns_used / max_turns），verdict 类型包括：continue / done / budget / cancelled / suppressed / steering / no_goal / **convergence** / **loop_restart**。
- Semantic Judge 特性：
  - 三段式 prompt：角色定义 + 严格 DONE 条件 + JSON 输出格式要求。
  - 前 N 轮跳过（Agent 需要时间开始工作）。
  - Fail-open 设计：判断失败默认继续工作，不阻塞进度。
  - Server 层实现多层 JSON 容错解析（直接解析 → markdown fence → inline 提取 → 前缀 fallback）。
  - **全栈上下文感知的精准多模态防作弊 (Context-Aware Precision Multimodal Judge)**：
    - 针对 GUI/浏览器 自动化任务易产生的“假阳性（Fake Success）幻觉”，Server 层的 `evaluate_semantic` 会进行物理拦截验证。
    - **意图级精准追踪**：Harness 层（执行引擎）会将本次执行流日志（`collected_messages`）全量透传给 Server 裁判。Server 层遍历查验，当且仅当日志中明确检测到 `browser_interact` / `computer_use` 等 GUI 工具的调用痕迹时，才标记需要视觉证据。
    - **物理强抓与降级**：判定需要视觉后，Server 才会通过 Gateway 从底层强拉取沙箱环境最新快照（截图），并包裹进 Vision 模型进行“眼见为实”的严苛核验。
    - 对于纯代码或运算等非 GUI 任务，哪怕沙箱后台残留着活着的浏览器进程，系统也会 100% 精准降级为纯文本评委。彻底阻断 Vision 模型的注意力干扰与高昂 Token 消耗，严格践行奥卡姆剃刀（0 误判 0 浪费）。
- Continuation Prompt 包含多层行为引导：
  - **Judge feedback 注入**：当 Semantic Judge 判定未完成时，其 reason（截断至 200 字符）被注入到 continuation prompt 的 "Previous evaluation feedback" 块中，使 Agent 直接知道哪里未达标而无需自行重新审视。
  - **Fidelity 防目标缩水**：明确告知 Agent 此目标跨轮持续，不要缩小目标范围或用更窄方案替代原始目标。
  - **Evidence-based 防历史幻觉**：要求以当前文件系统和外部状态为权威源，检查实际状态后再依赖对话上下文。
  - **Progress visibility 激活进度推送**：指导 Agent 在多步骤任务中主动调用 planner_tool 创建或更新计划，通过 TASKS_STEPS SSE 实现前端实时进度可视化；单步骤任务跳过。
  - **8 步 Audit Protocol**：含证据分级（证明/矛盾/弱证据/缺失）、范围匹配（窄检查不支撑宽声明）、必须证明完成而非仅未发现问题。
  - **Convergence awareness**：当 `convergence_window` 已设置且轮次足够时，注入收敛引导指令："如果连续多轮无新发现，主动声明 COMPLETE 并说明 convergence reason"。引导 agent 主动识别递减回报并优雅结束。
  - 行为指令：采取下一步行动、完成时声明、阻塞时报告。

### 6. Planner Tool (动态进度更新)
- 主 Agent 在执行过程中，通过调用 `planner_tool(action="update")` 来标记某个阶段完成。
- 工具**仅返回简短的摘要**（如 "Phase 1/5 completed"）作为 `ToolMessage` 追加到对话末尾，利用增量缓存机制，不破坏 System Prompt 的前缀缓存。
- 工具内部会触发 `TASKS_STEPS` 事件，供 Server 层转发给前端。

### 7. GoalControlPlane (前端全局控制面)
- 位于前端 Chat 窗口右侧的持久化面板。
- 接收 SSE 推送的 Plan 状态，实时渲染阶段进度（打勾）。
- 提供用户审批机制：处于 `PENDING_APPROVAL` 状态时，必须经用户点击"批准执行"，调用 `/approve_plan` 接口唤醒后端的 Harness 状态机，主 Agent 才会开始工作。
- **Execution Summary 卡片**：当 Goal 到达终态时，`GoalExecutionSummary`（修改文件数、测试通过率、Token/Cost、耗时）通过 `goal.metadata["execution_summary"]` 随 `GOAL_STATUS` SSE 事件推送至前端自动展示，无需额外 LLM 调用。

## 交互流程
1. 用户输入 `/goal 帮我写个爬虫`。
2. Server 收到请求，创建 Goal。
3. Harness 启动，`intercept_goal_and_plan` 发现没计划，调用 `PlannerAgent` 生成计划。
4. Harness 将状态置为 `PENDING_APPROVAL`，触发 `interrupt()`，执行流物理挂起。
5. 前端 `GoalControlPlane` 获取到计划，展示待办列表，等待用户审批。
6. 用户点击"批准执行"，调用 Server 接口。
7. Server 发送 `Command(resume=...)` 唤醒 Harness。
8. `PlannerMiddleware` 将计划蓝图注入 System Prompt，Agent 开始干活。
9. Agent 试图在未完成所有步骤时结束，被 `CompletionGuard` 拦截并打回。
10. Agent 乖乖执行，完成后调用 `planner_tool(update)`。
11. `planner_tool` 发出事件，Server 推送 SSE，前端 `GoalControlPlane` 更新打勾状态。

### 8. DAG 并发执行引擎 (DAG Executor)
- 将线性的 Plan 升级为有向无环图 (DAG)。
- `orchestrator.py` 中的 `execute_dag_plan` 支持基于依赖关系的并发执行，并支持通过 Yield-Resume 机制实现运行时动态并发裂变 (Swarm Fission)。
- 引入 `StateReducer` 解决并发状态读写冲突。
- 极大降低 IO 密集型任务的总耗时。

### 9. 主动缓存自愈 (Active Cache Healer)
- 监控长会话中的 Prompt Cache 命中率。
- 当命中率连续跌破阈值时，主动触发 `MemoryManager.compress_context()`。
- 保护大模型缓存，防止 Token 成本飙升和响应卡顿。

### 10. 优先级队列与自动串行执行 (Priority Queue)
- 当已有 ACTIVE goal 时，新提交的 goal 自动进入 QUEUED 状态（`GoalStatus.QUEUED`），存入持久化队列索引。
- 当前 goal 到达终态（COMPLETE/CANCELLED/BUDGET_LIMITED）后，`on_goal_terminal` 回调自动调用 `dequeue_next()` 取出下一个 goal。
- 被 dequeue 的 goal 自动设置 `auto_approve=True`，在 `GoalInterceptor` 中跳过 `interrupt()` 审批，直接执行。
- `trigger_goal_stream()` 启动后台 Agent stream，实现无人值守自动串行。
- Cron 任务与 Goal 队列联动：若 cron 执行时检测到活跃 goal，自动将 cron 任务以 goal 形式入队，避免并发冲突。
- 前端 `GoalQueueSection` 组件提供队列可视化、拖拽排序和取消功能。
