# sub_agents/

## Overview
Sub-agent subsystem — lifecycle management and configuration loading.

Detailed design: [SUB_AGENT_SYSTEM.md](SUB_AGENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-agent subsystem — lifecycle management and configuration loading. | — |
| branch_scoped_compaction.py | Core | Branch-scoped subagent artifact and structured summary compaction merger. Collects child trackers, extracts modified files, and enriches parent summaries. | ✅ |
| budget.py | Core | Delegation budget guard. Tracks descendant spawn count for one root run. | ✅ |
| builder.py | Core | Subagent construction helpers — tool filtering via DelegationCapabilityManifest + delegation_policy (READ_ONLY_SANDBOX configs also drop MCP tools that do not declare `readOnlyHint`), model resolution, token merge. | ✅ |
| checkpointer.py | Core | Shared crash-resilient SQLite checkpointer singleton (`SubagentSqliteCheckpointer`, `get_subagent_checkpointer`, `close_subagent_checkpointer`, `delete_subagent_checkpoint`, `drop_subagent_checkpoint_if_terminal`) with unwritable path `:memory:` fallback for subagent HITL approval thread isolation, SSOT hygiene cleanup, and cross-restart resumption. | ✅ |
| delegation_policy.py | Core | Server-extensible L1 leaf blocklist (`register_leaf_blocked_tools`). | ✅ |
| handover.py | Core | Structured subagent handover state (`AgentHandoverState`) and evidence (`HandoffFinding`) types with case-insensitive confidence normalization. | ✅ |
| hitl_tool_policy.py | Core | Import-safe HITL tool policy SSOT (`HitlToolPolicy`, `HITL_TOOL_POLICY`) used by `types.py` for leaf blocking. | ✅ |
| config_loader.py | Config | External config loader. YAML validation (Pydantic + Action Tool SSOT + regex tool names). | ✅ |
| event_forwarder.py | Core | Subagent event forwarder. Translates subagent events into progress and log events. Includes staleness detection (`is_stale`, `_check_and_emit_stale`) with configurable thresholds and in-tool multiplier. `internal=True` silences all emissions (internal verification nodes stay off user-facing surfaces). | ✅ |
| executor.py | Core | SubagentExecutor aggregate root (mixin MRO: Retry → Attempt → Delegation). Re-exports helper functions for tests and notifications. | ✅ |
| executor_retry_mixin.py | Internal | Retry loop, workspace isolation (immediate sync_back → `apply_isolated_sync_back_with_snapshots` before return; merge fail → merge_warning + result metadata), hooks, graceful cancellation (`run_with_retry`); every run closes with exactly one SUBAGENT_STOP (payload carries `status`): an attempt's returned result of any status goes through `close_run`, each failure exit and cancellation build their result with `finish_failed` (reading a failed run's streamed text with `read_partial_output`) and close through `close_run`, which delivers STOP once even when a cancellation lands mid-delivery. Extends the attempt mixin. | ✅ |
| executor_attempt_mixin.py | Internal | Single child-agent attempt: fork context, event forwarding, handover parsing, taint propagation (`_inherit_parent_context`, `_run_single_attempt`); the answer text (result and `partial_output`) accumulates in `AnswerDraft`, so a recovery restart replaces the in-flight segment instead of repeating it; on failure the text rides on the exception via `attach_partial_output`; it never fires SUBAGENT_STOP, which is the retry loop's job. Extends the delegation mixin. | ✅ |
| executor_delegation_mixin.py | Internal | Orchestrator-role delegation meta-tool attachment (`_attach_child_delegation_tools`). | ✅ |
| executor_helpers.py | Internal | Pure helpers: fork filter, error compaction, `_auto_vault_or_truncate` (vault + inline artifact + file_read hint), handover parse (via `parse_llm_json_object`, robust against fences/prose/trailing commas), cascade cancel, `attach_partial_output` / `read_partial_output` (the failed attempt's text on its exception, cut to a character budget on read). | ✅ |
| manager.py | Core | Subagent lifecycle manager. Core state tracking, validation, cleanup, capacity, and observability. Inherits spawn/execution from `_manager_spawn` and control operations from `_manager_control`. Maintains strong global registry `COMPLETED_SUBAGENT_RESULTS` (TTL 1h / 1000 FIFO) so terminal results survive after the parent gateway session ends. | ✅ |
| _manager_spawn.py | Internal | Spawn and execution mixin for SubagentManager (`_run_subagent*`, `spawn_child`). SSOT for workspace isolation enforcement (`apply_spawn_workspace_isolation`). `spawn_child` accepts `internal: bool` — internal nodes are hidden from SSE/global events, teammate registration, and the shared notification queue. No wall-clock timeout by default; hard timeout only when `timeout_seconds` is explicitly set. | ✅ |
| _manager_control.py | Internal | Control plane mixin for SubagentManager (`cancel_child`, `steer_child`, `list_children`, `wait_children`, `drain_notifications`, `run_alternatives`, `run_chain`, `run_council`, `run_with_verification`). `list_children` filters out `internal` nodes (running and completed) so user-facing trees only show business tasks. | ✅ |
| session_tree.py | Core | Merge gateway + ACTIVE_SUBAGENTS rows (incl. strong `COMPLETED_SUBAGENT_RESULTS` terminal history); match REST uuid against `chat_` / `chat_chat_` session ids; registry cancel-all helper. | ✅ |
| notifications.py | Core | Push-based notification formatting for subagent completion events and active subagent context injection. | ✅ |
| strategic_advisor_schema.py | Core | Declarative 4-section schema specification for bundled strategic advisor subagents (`StrategicAdvisorySchema`, read-only safety guard `validate_strategic_readonly_safety`, and prompt compilation `compile_strategic_advisor_prompt`). | ✅ |
| role_chain_schema.py | Core | Declarative subagent role chain presets and prompt guidance compiler (`RoleChainPreset`, `RoleChainStage`, golden presets `implement_review_fix`, `clarify_scout_worker`, `watchdog_guard`, `editorial_publish`, and `compile_role_chain_guidance` with max review rounds cap). | ✅ |
| SUBAGENT_NOTIFICATION_STRATEGY.md | L2 | Cache-safe subagent notification delivery (SSE + wakeup user message) | — |
| orchestrator.py | Core | Subagent composition patterns — chain, batch, alternatives (text compare; deferred isolated workspaces discarded), and `run_council` (multi-expert cross-review). Delegates verification to `_orchestrator_verification` and council to `_orchestrator_council`. | ✅ |
| spawn_prep.py | Core | Shared spawn prep SSOT (coerce_spawn_readonly floor incl. read-only parent handle, readonly, isolation, child context built from the parent's authoritative fields only, sanitize store via merge_metadata). | ✅ |
| spawn_capability.py | Core | Single producer of the subagent OCap handle: scope = the parent's workspace plus `context_files` authorized by the parent's path policy (`authorized_context_paths`), attenuated from the bound parent handle when one exists. The caller binds the result with `capability_scope`; that binding is the only channel, so enforcement and grandchild derivation read the same handle. `derive_verifier_capability` mints a verifier's handle: the delegating agent's reach restricted to READ and EXECUTE. | ✅ |
| verifier_selection.py | Core | `resolve_verifier`: the one place the delegate and DW entries pick a worker's verifier (defaults to the worker's type; an unresolved type falls back to the worker's config as resolved, before readonly edits that would strip the command tool) and force it `READ_ONLY_SANDBOX`, leaf scope with no delegation, plus the spawn policy (memory-write block). Runs the spawn's real `filter_tools` and raises `VerifierUnavailableError` before any worker spawns when the verifier lacks `bash_code_execute_tool`, since none of its PASS verdicts could count; an agent factory may still narrow the tools at build time, which the execution-evidence gate backstops. | ✅ |
| _orchestrator_council.py | Internal | Council orchestration — multi-expert parallel analysis with cross-review debate and chair synthesis, COUNCIL_PHASE event emission. | ✅ |
| _orchestrator_verification.py | Internal | Adversarial verification retry loop (`run_with_verification`). Supports standard single verifier, `auditor_blind` (worker self-praising narrative stripping + removal of files the verifier added), and `multi_skeptic` (delegates voting to `_multi_skeptic.py`). Accepts a business `task_id`: the first worker runs under that visible id (`internal=False`) while retry workers and verifiers spawn as internal nodes; the final outcome is mirrored onto the business `SubAgentResult`. A verifier round without a conclusive verdict ends the loop as BLOCKED with an `INCOMPLETE` note instead of triggering worker rework. A rework worker that fails ends the loop with its own error, never the earlier round's verdict. Delegates single-round verifier spawn to `_verifier_round.py`. | ✅ |
| _multi_skeptic.py | Internal | `vote_with_skeptics`: three blind skeptic rounds in parallel, merged by majority (PASS needs 2 conclusive PASS votes). A skeptic that crashed or passed without execution evidence casts no vote; no conclusive vote, or a lone PASS that proves no defect, yields `None`. | ✅ |
| _verifier_round.py | Internal | Single-round verifier spawn (always `internal=True`) with a per-round verdict sink and `submit_verdict` kept in the verifier's allowlist (a non-empty preset allowlist would otherwise strip the verdict channel), run under the READ+EXECUTE verifier handle and an execution-evidence scope (a PASS without a launched process yields no verdict), workspace mutation detection with removal of verifier-added files (`revert_workspace_mutations`), and `verify_worker_output()` (the Cron post-run entry; returns `None` when the round is inconclusive). | ✅ |
| _verification_parsing.py | Internal | `VerificationVerdict` parsing + VERIFICATION_VERDICT SSE emission. Parses the verifier verdict via `parse_llm_json_object(require_key="verdict")` (robust against fences, prose, bare control chars, trailing commas). | ✅ |
| _workspace_diff.py | Internal | Lightweight stat-based workspace file change detection (`take_workspace_snapshot`, `format_workspace_diff`) and `revert_workspace_mutations`, which deletes files added during a verifier round (modified files are not restored). | ✅ |
| prompts.py | Core | Default prompt templates for multi-agent coordination. | ✅ |
| registry.py | Core | Subagent configuration registry and loader. Provides global config registration and lookup. | ✅ |
| result_output.py | Core | Subagent result payload type (`SubAgentOutput`: answer text, or a dict carrying isolation merge metadata) and `answer_text`, the single reader of a payload as text. | ✅ |
| types.py | Config | Subagent subsystem core type definitions. Defines all subagent-related data types, enums, protocols, DelegationCapabilityManifest (with `cron_manage_tool` leaf blocking), SubagentConfig (including `timeout_seconds: int | None = None` — no wall-clock timeout by default, `__post_init__` normalizes ≤0→None and enforces min 30s floor; `max_error_chars` for error compaction control; `stale_after_seconds`/`in_tool_stale_multiplier`/`stale_auto_cancel` for staleness detection), CouncilOpinion, CouncilResult, VerificationSummary, HandoffFinding, AgentHandoverState (with summary, findings, citations, artifact_refs, context_artifacts), and SubAgentResult.verification. `SubAgentResult.internal` marks framework-internal nodes (verification workers/verifiers) hidden from user-facing trees. | ✅ |
| workspace_isolation.py | Core | Workspace isolation for subagent execution. COW clone with ignore-pattern filtering (node_modules, .git, dist, etc.), max_bytes safety guard, and efficient file counting. | ✅ |

**Tests mocking executor internals** must patch the defining module (e.g. `executor_attempt_mixin.build_child_agent`), not the aggregate `executor` module.

| Submodule | Description |
|-----------|-------------|
| multiplexer/ | 持久化多智能体会话多路复用器与跨 Agent 互视/指导机制（支持多会话切片管理、无头工作者标记、inspect_agent_session 与 instruct_agent）。详见 [multiplexer/_ARCH.md](multiplexer/_ARCH.md)。 |
| device_mesh/ | 边缘设备网格与多节点分布式调度器（支持局域网/Tailscale 边缘设备注册、Token 配对门禁、心跳遥测监测与多智能体跨节点命令派发工具）。详见 [device_mesh/_ARCH.md](device_mesh/_ARCH.md)。 |
| todo_store/ | 跨进程/跨插件共享 Todo 计划声明存储与控制字符安全清洗 HUD 只读投影子系统（支持严格 20 项与字符上限门禁、双向 C0/C1 与 ANSI 剥离清洗、只读 HUD 投射与标准元工具）。详见 [todo_store/_ARCH.md](todo_store/_ARCH.md)。 |
| ralph_loop/ | Ralph 式 Fresh-Agent 多轮循环与极简五字段强交接系统（支持长任务每轮启动无历史全新子代理、共享工作区物理文件协同、五字段容量硬顶与尝试满三轮阻断防御规则）。详见 [ralph_loop/_ARCH.md](ralph_loop/_ARCH.md)。 |
| advisor_channel/ | 双模型实时旁路军师评审通道（基于 oh-my-pi 架构，为智能体挂载独立模型与 Context 窗口的 Advisor 军师角色，按 aside/concern/blocker 三级分层实时审查与硬阻断熔断）。详见 [advisor_channel/_ARCH.md](advisor_channel/_ARCH.md)。 |
| supervision_hub/ | 子代理实时监管抽屉引擎（基于 oh-my-pi 架构，提供并发 Worker 实时花名册聚合、环形 Live Transcript 执行轨迹缓冲区与 Steer/Kill/Revive 三大生命周期干预调度）。详见 [supervision_hub/_ARCH.md](supervision_hub/_ARCH.md)。 |
| conflict_gate/ | 多 Bot 并行产出冲突对账与合并前拦截门（聚合写集指纹、检测 Hash 碰撞并触发 conflict_pending 阻断、提供四策略对账解决器）。详见 [conflict_gate/_ARCH.md](conflict_gate/_ARCH.md)。 |
| mcp_scope_gate/ | MCP 发现工具按数字员工/Agent 作用域严格隔离门禁（对标 StaffDeck，支持 Profile 级 MCP Server/工具白名单绑定、动态发现候选集 Fail-Closed 过滤与越权调用拦截）。详见 [mcp_scope_gate/_ARCH.md](mcp_scope_gate/_ARCH.md)。 |
| agent_operations/ | Agent-Owned 多智能体协同操作体系（对标 OpenClaw，收敛并隔离多 Agent 协同中的 Provider 设置、模型参数、能力解析 Resolver、白名单 Allowlist 与操作级错误堆栈 Error Stack，维护标准 List-form Agent 花名册）。详见 [agent_operations/_ARCH.md](agent_operations/_ARCH.md)。 |
| durable_dispatch/ | Hermes Fabric 确定性远程分发与持久化对等日志内核（对标 Hermes GPT，支持 WorkContract 契约、Fail-Closed 执行前策略重校验、单调递增双向对等日志 Durable Journals、有界证据准入门禁与崩溃后幂等自愈恢复）。详见 [durable_dispatch/_ARCH.md](durable_dispatch/_ARCH.md)。 |
| report_fifo/ | 子智能体回报路径实时唤醒、Step 边界报告结算保序与无人值守多命名实例体系（对标 DeepSeek Harness，支持 next-step steer 唤醒、Report-before-Settlement FIFO 严格保序队列与 permissionMode 无人值守策略）。详见 [report_fifo/_ARCH.md](report_fifo/_ARCH.md)。 |
| failure_facts/ | 子智能体脱敏结构化失败事实与安全归因诊断协议（对标 DeepSeek Harness，提供单行安全诊断 Header、4096 字节有界限制、六大生命周期阶段、九大故障分类、敏感凭证脱敏与自愈建议）。详见 [failure_facts/_ARCH.md](failure_facts/_ARCH.md)。 |
| debate/ | 多智能体动态协同工作间与辩论流任务看板联动引擎（对标扣子桌面端项目工作群，支持 Leader 任务拆解、专员辩论质询、防无效车轮战自动收敛与 Kanban 任务双向状态绑定）。详见 [debate/_ARCH.md](debate/_ARCH.md)。 |
| cli_adapter/ | 多源异构 Agent 外部进程桥接与 CLI 工具标准化适配器（对标扣子桌面端与 Hermes Conductor，支持 Claude Code/Codex/OpenClaw/Stdio CLI 进程挂载、生命周期调度、超时熔断与 ANSI 清洗凭证）。详见 [cli_adapter/_ARCH.md](cli_adapter/_ARCH.md)。 |
| checkpoint/ | Subagent checkpoint utilities package. Includes orphan recovery for automatic resumption after restart. |
| cross_examination/ | Omni-agent unified single-entry dispatch and split cross-examination subsystem (Item 314). See [cross_examination/_ARCH.md](cross_examination/_ARCH.md). |
| teams/ | Durable Agent Teams 会话内自组网、去中心化 Peer Mailbox、CAS 版本化共享任务板与实时看板引擎（对标 DeepSeek Harness，支持隐式 Root Lead、kebab-case 具名 Roster、CAS 乐观锁与严格 DAG Blocker 依赖拓扑校验、断电冷恢复对等邮箱）。详见 [teams/](teams/)。 |
| budget_scaling/ | 子任务并发度弹性提升与工具调用预算自动无损迁移体系（对标 Hermes Agent v0.20.2，默认并发提升至 10、单任务预算扩容至 250、旧版默认值零中断无损平滑迁移、80% 动态自适应水位预警心跳保护）。 |
| review_loop/ | 多视角并发子智能体评审与有界自愈复审闭环体系（对标 Pi / oh-my-pi 与 dsh-agent-teams 质量门禁，三视角正确性/测试/反过度设计并发聚焦会诊、有界 N 轮自愈循环状态机、收敛检测与退出判定）。 |
| failure_policy/ | 子智能体 mid-task 失败 per-role 声明式自愈策略与自适应重启/规格重部署/升级/跳过决策引擎（对标 Hermes 社区最佳实践，支持 RESTART_FRESH、REDEPLOY_SPECS、ESCALATE_PARENT、SKIP 四大决策及有界重试熔断防线）。 |
| mcp_summarizer/ | 重 Payload MCP/大文档获取专用子 Agent 预置与结构化摘要防污染引擎（支持重型 Payload 自动判定、结构化摘要工件提取提取-38.4% Token、与未隔离主会话污染审计诊断 Doctor）。 |
| lifecycle_toolchain/ | 原生 Subagent 细粒度生命周期管控工具链（支持 spawn/wait/list/send_input/kill 原子原语、线程安全任务状态机、动态纠偏注入、异步等待聚合与超时自动熔断防线）。 |
| mixed_fleet/ | 混合舰队预置（支持本地隐私记忆脑 Local Brain 与远端 24/7 常驻沙箱执行器 Remote Executor 协同、结构化 Markdown 交接契约流转与双向心跳监控）。 |
| zero_token_contract/ | 舰队可视化零 Token 契约引擎（对标 Hermes3D，针对 Fleet Canvas、3D Office、虚拟宠物等可视化视图实行 100% 确定性运行时事件订阅镜像，Doctor 硬拦截任何违规 LLM 调用，严格保证可视化层 0 Token 消耗）。 |
| cross_surface_bridge/ | 跨界面智能体活动对话汇入桥引擎（对标 Hermes3D office-conversation-bridge，支持 Tauri 桌面端、CLI 终端、Cron 计划任务与远端只读办公室克隆活动的轻量汇入与有界最近投影，避免全量 transcript 冗余同步）。 |
| multi_lane/ | Pi Harness v2 会话内多 Lane 并行执行与共享追加树引擎（对标 pi harness-v2.md §2/§3/§8，同会话支持多 Lane 并行执行如 Slack Channel 下多 Thread，共享 append-only tree，每 Lane 独立维护 leaf 与 op log，严格保证单 Lane 最多 1 个 open operation，单写入协调器保障线程安全与无损并发）。 |
| session_fork/ | Pi Harness v2 确定性子会话派生与安全重放重接原语（对标 pi harness-v2.md §17，基于 f(parentSessionId, toolCallId) 纯确定性派生 childSessionId，崩溃/重放 Safe Replay 时自动 reattach 现有 child 杜绝 twin 孪生子会话污染；支持 repo.fork(scope=branch|tree) 仅复制历史节点且保持新子会话初始 IDLE 纯净状态）。 |
| token_budget_governance/ | 单模型多 Agent 共享上下文 Token 预算治理与路由开销可视化引擎（对标 BkashJosi 与 RepoAvcisi 多 Agent 路由实践，提供共享模型配额管控、扇出前预检 fail-closed 拦截、Routing Overhead 与 Execution Payload 精准归因核算、以及重复 handoff 烧 Token 的 Doctor Nudge 智能预警防线）。 |
| pipeline_integrity/ | 开源可 inspect 工作流 · Handoff/Approval/Delivery 断点 Lint 与 Doctor 告警诊断包（对标 simplydt 与 BkashJosi 多 Agent 流水线断点治理，提供交接元数据缺失、无审批门禁直通 Delivery、交付产物缺失与无验证步骤四大断点规则 Lint 审计、可审查决策链提取与一键 Auto-Heal 自动补全自愈）。 |
| specialist_summoning/ | 对话流自然语言/@召唤子专家协同与上下文结构化汇聚包（对标豆包与 WorkBuddy 垂直专家随时唤醒协同，支持输入框 @ 显式召唤与自然语言意图感知、轻量独立沙箱子会话执行避免主会长上下文污染、以及结构化产物工件卡回流主对话流）。 |
| swarm_mesh/ | SwarmForge 动态 Agent 集群拓扑编排器与多智能体网格通信拓扑（支持声明式 Star/Hierarchical Tree/Peer Mesh/Pipeline/Ring 五大拓扑编排、平滑无损运行时拓扑切换、弹性扩缩容、单节点带状态热迁移、P2P 单播/组播/广播消息总线、以及共享黑板乐观版本自增治理）。 |
| workspace_inheritance/ | 子智能体工作区根规则与项目上下文自动继承体系（对标 Hermes Agent，在构建子智能体系统提示词时自动继承父级已解析的工作区绝对路径，严格遵循 .rules > AGENTS.md > README.md 优先级链条动态抽取架构红线与安全规范，实施 2K Token 上限控制与差分摘要裁剪，杜绝子 Agent 违背架构规范与越界违规）。 |
| `replay_dedup/` | 多智能体历史工具调用回放合并与状态机同步增强机制（对标 jiuwenclaw PR #5274，提供连续等幂/只读工具调用紧凑批处理聚合与 Token 节省率核算、写操作绝对隔离保护、单调递增子智能体状态机流转、以及心跳租约看门狗防假死自愈）。 |
| `cloud_edge_relay/` | 云端-本地混合沙箱双向工件接力与网络受限爬取调度包（对标 jiuwenclaw PR #5289，支持 CAS 乐观版本校验与 Append-Only Chunk 链式增量更新、跨节点工件双向同步、SSRF 安全防护与本地网络出口受限资源调度接力）。 |
| `virtual_room/` | 多人多 Agent 实时协作虚拟空间、文件系统级协同与能力借用套件（对标 Tutti·VM，支持身份/执行/空间三权分立、细粒度文件块写租约锁与冲突自动消解、跨用户 Agent 零凭据借用网关与沙箱服务全员即时 Live 端口预览）。 |
| `swarm_offload/` | 高并发子智能体集群调度与透明云沙箱算力卸载套件（对标 OpenAI Tibo 访谈算力瓶颈转移，支持 10-15 并发子智能体高吞吐扇出、宿主机 CPU/内存/活跃任务物理资源水位实时监控、水位超限自动透明卸载至云端沙箱与 vault:// 零拷贝工件指针）。 |
| `visual_timeline/` | 多智能体可视化时间轴与单 Agent 节点精准 Cherry-Pick 撤销引擎（对标 Tutti·VM，支持多维时间轴日志检索、单节点原子精准反向补丁撤销、重叠依赖冲突检测与无损协作保护）。 |
| `clean_code_pipeline/` | Clean-Code 装配流水线与架构依赖关系 Lint 检查引擎（对标 Clean-Code Assembly Pipeline，提供 Specifier->Coder->Cleaner->Hardener->QA 五阶段单向步进工件交接、AST 静态 import 解析分层架构与循环依赖校验门禁、以及自动 DIP 依赖倒置重构修复建议推导）。 |
| `fusen/` | 多智能体轻量级 Fusen 便签看板与共享状态同步协议（对标 DojoAgents #139，提供无中心轻量状态便签发布与解决、blocker/ready_for_review/cache_hint 分类检索、亚毫秒级阻塞判定与自动过期清理）。 |
| `vertical_presets/` | 五大垂直角色 Persona 预设与单 Bot 隔离沙箱测试引擎（对标 Hermes 行业最佳实践，提供 Life Admin、Office Manager、Clipper、Chief of Staff、Sales Team 五大预置角色，支持单 Agent 隔离沙箱执行、指标与日志捕获，以及 A2A 通信流向追踪与成环死循环检测）。 |
| `council/` | 高阶决策多模型审议委员会与交叉仲裁共识协议引擎（对标 council-of-high-intelligence，提供 3+ 异构模型盲审提案收集、匿名交叉质询与反驳答辩轮次推进、置信度加权共识裁决合成器与少数派异见归档）。 |
| `kanban_dispatcher/` | 可视化看板多智能体任务分发与卡片级自动交接流引擎（对标 hermes-agent 看板编排实践，提供 Backlog/Researching/Developing/Reviewing/Done 五泳道卡片生命周期治理、泳道跃迁跨 Agent 自动打包交接与工件继承、微型进度条追踪以及阻塞判定与自愈调度）。 |
| `cli_passthrough/` | 外部 CLI 子代理适配桥梁与官方订阅无感穿透调度器引擎（对标 DeepSeek Harness dsh v0.1.0-rc.8 Profile Bundle 规范，提供 Claude Code/Codex/Cursor CLI 可插拔非交互静默执行、BYOS 用户自有官方订阅复用、委派前如实隐私披露门禁、工作区文件访问边界防越权继承与不可篡改 SHA-256 出站账本记录）。 |
| `dag_orchestrator/` | 多智能体 DAG 可视化编排器与带状态断点冷恢复和双向反馈闭环引擎（对标 dsh-agent-teams 插件规范，提供自然语言一句话建队与 DAG 依赖图解析、Kahn 算法拓扑排序与无环保障、Checkpoint 节点工件持久化与零重复冷恢复、以及下游审查失败向指定上游节点发起双向驳回并联动重置下游依赖分支的有界动态纠偏闭环）。 |
| `kanban_queue/` | 多智能体持久任务看板队列与 12 路大规模并行 Dogfooding 运行器套件（对标 Hermes Kanban 与 batch_runner 规范，提供 5 态流转状态机、编排者与 Worker 九大协同工具链、4 小时僵死心跳自动回收、Swarm 四阶段拓扑与 `[swarm:blackboard]` 结构化共享黑板、自动 Triage 细化与 Fan-out DAG 分解、Git Worktree 独立工作区隔离与防失控热熔断、Goal-Mode 验收标准循环、12 路多进程并行调度与 `--resume` 检查点恢复、以及 HuggingFace 兼容标准 JSONL 轨迹沉淀）。 |
| `diamond_graph/` | 图工程钻石拓扑模式并行调度与盲审对抗式交叉审计套件（对标 Graph Engineering 工业级图工程规范，提供 Fan-out -> Reduce -> Synthesize 钻石三段式执行引擎、静态分析剔除伪因果箭头的假依赖修剪器、Dead-Node Census 容灾哨兵 N 派发 N 回收保障、CoT 绝对物理剥离的独立上下文盲审对抗团多数表决机制、以及 Exit Code 0 / SHA-256 哈希匹配客观不可篡改真实事实锚点校验门禁）。 |
| `coauthoring_ledger/` | 人机多方围绕单一动态文档协同编辑的状态机账本与冲突仲裁中枢（对标 WorkBuddy 第三阶段办公协同逻辑，提供人类用户与绑定 AI Agent 的三层协作关系模型、细粒度文档块生命周期与租约锁、携带意图原因的不可变增量账本状态机、作者贡献度透视追溯、以及人类优先/时间戳/隔离暂存提议的多策略冲突仲裁引擎）。 |
| `socket_mesh/` | 基于 Unix Socket / 命名管道的极简去中心化同机多 Agent 协同网格与原子信封协议（对标 Pi coms.ts & coms-net.ts，提供基于本地文件系统的零 Broker 注册自发现、跨平台 IPC 端点、标准原子信封通信协议、Hops 严格防环路熔断机制、In-flight Pending Reply 异步 Future 追踪与 coms_list/send/await/ping 内置协同工具链）。 |
| `bot_forge/` | 对话式智能体与团队工厂、确定性创建流水线与建造者权限安全边界套件（对标 Pi specs/pi-pi.md 与 Hermes Bot Forge 出货形态，提供 Anti-recursion 防递归繁衍守卫、Permission Attenuation 权限收敛边界门禁、名称唯一性与语义职责重叠分析、Zero-model 干跑就绪核验、以及原子化 Transactional Rollback 状态机事务回滚中枢）。 |
| `external_bundle/` | 异构外部第三方 Agent 容器化收编与子代理 Profile Bundle 调度桥接器（对标 DeepSeek Harness RC.8 subagent-claude-code 与 subagent-codex 调度层，提供 Claude Code/Codex/Gemini CLI 规范封装、工作区沙箱目录继承与防越权校验、破除单一 backend 锁的无锁高并发多实例多路复用调度器、终端 ANSI 格式清洗与结构化工件统一重塑）。 |
| `kanban_orchestrator/` | 多智能体持久任务看板调度中枢与卡片 DAG 依赖拓扑分发器（对标 Hermes Kanban 编排生产实践，提供 Backlog/Todo/In Progress/Review/Done/Blocked 六泳道状态机、DFS 无环依赖拓扑计算、卡片依赖完成自动解锁级联 Auto-Unblock Cascade、卡片级沙箱隔离目录 tasks/{card_id} 与工件原子挂载）。 |
| `fleet_router/` | 跨机分布式舰队 Profile Rail 全景导航轨、多网关拓扑自愈、离线缓冲与跨机工件中继中枢（对标 Hermes Desktop PROFILE RAIL 舰队级扩展实践，提供 Darwin/Linux/Cloud 多网关连接池、心跳遥测与健康度自感知、断网离线指令 FIFO 缓冲与自愈排空重连 Auto-Healing Flush、Agent 宿主拓扑上下文自动注入、以及 SHA-256 跨网关安全工件中继验证）。 |
| `graph_triage/` | 图工程自适应适用性评估门禁与并发 Token 预算熔断套件（对标 Graph Engineering 行业实践与成本失控治理规范，提供单步/探索对话/纯时序流水线/多路重型并行启发式准入评估门禁 `GraphApplicabilityTriageGate`、扇出前置 Token 预估与硬上限预算熔断器 `PredictiveBudgetGuard`、以及基于剩余预算的动态自适应并发节流与危急状态提前局部优雅归约引擎 `ElasticConcurrencyReducer`）。 |
| `orthogonal_reviewer/` | 正交双视角审查门禁与零偏见盲审子代理（对标 Codex 双审查子代理实践，彻底终结大模型自我合理化偏见；提供注入完整设计意图的 Reviewer A、物理隔离历史 CoT 纯看 Diff 与契约的盲态 Reviewer B、以及缺陷语义去重、严重度裁决与定向自动修复闭环仲裁器 `OrthogonalReviewArbiter`）。 |
| `live_transcript/` | 子 Agent 实时透明 Live Transcript 轨迹流、后台委派任务持久化恢复账本、单次命令绑定 Smart Approvals 与 /deny 交互反馈、以及 MoA 角色细粒度推理强度动态分配套件（对标 Hermes v0.19 委托透明与持久化体系，消除多 Agent 协作盲区与后台任务丢失风险）。 |




## Key Dependencies

- `utils`
