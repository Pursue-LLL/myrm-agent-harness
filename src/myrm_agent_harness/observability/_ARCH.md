# observability/

## Overview
Observability tools for Myrm Agent framework. Provides Prometheus metrics, auth failure detection, active health diagnostics, and request tracing context for log correlation.

**Naming disambiguation** (same word, different packages — do not merge or relocate):

| Path | Responsibility |
|------|----------------|
| **`myrm_agent_harness.observability`** (this package) | Metrics, health probes, ContextVar log tracing |
| `myrm_agent_harness.agent.streaming.broadcast` | Chat tool SSE (`ToolBroadcastBus`) |
| `myrm_agent_harness.infra.pubsub` | Server business SSE (`PubSubBus`) |
| `myrm_agent_harness.infra.tracing` | **OpenTelemetry** distributed tracing (optional `[observability]` extra) |
| `toolkits/*/observability.py` | Per-toolkit business-neutral operation DTOs |

`toolkits/` may depend on this package per [toolkits/_ARCH.md](../toolkits/_ARCH.md) Allowed Dependencies.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observability tools — auth detection, tracing primitives re-export. | ✅ |
| auth_detector.py | Core | Authentication failure detection for circuit breaker logic. | ✅ |

| Submodule | Description |
|-----------|-------------|
| audit_trail/ | Dual-track audit log, redaction, and compliance dossiers. |
| digest/ | Health evaluation digest. |
| metrics/ | Generic metrics utilities; Prometheus counters require `[observability]` extra (NoOp fallback otherwise). |
| diagnostics/ | Framework-level self-inspection — health probes (incl. gateway runtime vitals), benchmark hook registry, and diagnostic protocol. |
| thought_telemetry/ | 长推理思考链（CoT）流式遥测与失控死循环守护子包：毫秒耗时度量、自纠偏步骤特征识别、N-gram 死循环熔断与软中断纠偏。 |
| timeline_visualizer/ | 任务执行透视镜与技能调用时序可视化核心引擎：毫秒级耗时追踪、时序瀑布流、步骤状态树与插嘴打断。参见 [timeline_visualizer/_ARCH.md](timeline_visualizer/_ARCH.md)。 |
| tracing/ | ContextVar-based request tracing (trace_id / session_id) with logging.Filter and JSON formatter. |
| context_retrieval/ | 上下文分层检索下钻决策树追踪与剪枝留痕套件：目录递归下钻、分值比对、动态阈值剪枝判定与检索全景轨迹快照。参见 [context_retrieval/_ARCH.md](context_retrieval/_ARCH.md)。 |
| resource_metering/ | 物理硬件占用与认知 Token 混合开销全景对账单套件：沙箱执行秒数、规格加权折算、Token 认知计量与预算防超支熔断。参见 [resource_metering/_ARCH.md](resource_metering/_ARCH.md)。 |
| labor_acceleration/ | 白领劳务效能加速度量化与生产力 ROI 计量引擎：人工工时等效换算矩阵、单任务加速倍率（如 96×）与投资回报率全景看板。参见 [labor_acceleration/_ARCH.md](labor_acceleration/_ARCH.md)。 |
| diagnostics_bundle/ | 端内沙箱现场全景诊断打包与自愈凭证引擎：生命体征抓取、PII/Secret 深度脱敏与防篡改 HMAC 校验和。参见 [diagnostics_bundle/_ARCH.md](diagnostics_bundle/_ARCH.md)。 |
| workflow_throttle/ | 海量并发 Agent 编排流水线实时 Token 燃速度量与阶梯式动态风控限流熔断引擎：滑窗燃速平滑、50%/80%/100% 阶梯治理与自适应降级。参见 [workflow_throttle/_ARCH.md](workflow_throttle/_ARCH.md)。 |
| coordination_friction/ | 人机协调摩擦度量、人工介入衰减曲线与协同效率 ROI 量化记分板引擎：HITL 介入密度统计、多轮监督衰减曲线与注意力时间净节省折算。参见 [coordination_friction/_ARCH.md](coordination_friction/_ARCH.md)。 |
| cron_doctor/ | Cron 自动化任务舰队全景健康体检医生与预防性隐患自查引擎：6 大健康门禁只读扫描（执行/交付/回执/调度逾期/脚本/工作区）、隐患聚合诊断与外科手术式修复指引。参见 [cron_doctor/_ARCH.md](cron_doctor/_ARCH.md)。 |
| cumulative_delivery_budget/ | 多智能体整轮交付全生命周期成本核算、未知用量审计账本与硬预算熔断管理包：二元双账本（Trial vs Cumulative）、未计量调用保守计提与 70%/100% 阶梯熔断。参见 [cumulative_delivery_budget/_ARCH.md](cumulative_delivery_budget/_ARCH.md)。 |
| agentic_traffic/ | AI Agent 流量精准解构、跳出归因与静默审判可观测性套件：Cursor/Claude/Windsurf 等高精识别、AEO 页面诊断探针与 4 阶梯转化漏斗。参见 [agentic_traffic/_ARCH.md](agentic_traffic/_ARCH.md)。 |
| sanitized_debug_dump/ | 一键安全脱敏诊断包生成、敏感凭据物理抹除与加密阅后即焚分享管理包：Zero-Leak 正则抹除、环境体征快照与 48h/3次自毁分享短链。参见 [sanitized_debug_dump/_ARCH.md](sanitized_debug_dump/_ARCH.md)。 |
| token_economics/ | 长任务 Token 经济学透明透视、99% 缓存节流真实收益与算力账单防刺客引擎：多模型 Prompt 缓存成本 ROI 换算、单位成本滑动基线漂移归因与软硬预算熔断刹车。参见 [token_economics/_ARCH.md](token_economics/_ARCH.md)。 |
| delivery_dossier/ | 跨智能体任务交付证据卷宗、资产真实有效性与摩擦浪费可观测性引擎：5大维度不可变交付证据（Spec/指纹/工具/物理凭证/验收）、分层资产效能度量与摩擦刺客资产识别。参见 [delivery_dossier/_ARCH.md](delivery_dossier/_ARCH.md)。 |
| rate_limit_governor/ | 客户端主动限流预测阀门、按模型动态配额自适应调度与零 429 顺滑放行引擎：多厂商响应头侦听、前置微延迟平滑削峰 (200~500ms) 与多并发子任务配额切片隔离。参见 [rate_limit_governor/_ARCH.md](rate_limit_governor/_ARCH.md)。 |
| context_optimization/ | 上下文拦截节流审计器、跨工具 Token 节省率分析与工程信号七维决策套件：每工具节流效益量化战报、折算真金白银、7 维工程障碍模式诊断与 4 角色研发效能视图。参见 [context_optimization/_ARCH.md](context_optimization/_ARCH.md)。 |
| reasoning_semantics/ | 推理 Token 计费语义契约、按提供方归一化与重复计数回归守卫套件：明确不变量契约、多提供商策略适配映射、零重复累加消除与运行时诊断自愈。参见 [reasoning_semantics/_ARCH.md](reasoning_semantics/_ARCH.md)。 |
| org_spend_limit/ | 团队共享智能体组织月度限额、逐 Query 标签归因与超限熔断套件：群聊/私信分级记账、80% 软预警与 100% 硬限额熔断、按身份/Surface 审计归因。参见 [org_spend_limit/_ARCH.md](org_spend_limit/_ARCH.md)。 |
| knowledge_compounding/ | 知识复利健康度记分板与五大指标闭环套件：统一只读聚合重复错误率、知识命中率、人工纠正次数、任务一次通过率、过期知识占比，提供复利层级判定与劣化报警检测。参见 [knowledge_compounding/_ARCH.md](knowledge_compounding/_ARCH.md)。 |
| turn_context_provenance/ | 会话逐轮上下文注入来源清单、内容指纹快照与可复现审计套件：记录 System Prompt、Memory、Skill、MCP、Workspace File 注入清单、计算 SHA256 指纹与跨轮差异比对。参见 [turn_context_provenance/_ARCH.md](turn_context_provenance/_ARCH.md)。 |
| deployment_funnel/ | 部署漏斗监控与反馈提醒回路套件：4 阶段用户转化漏斗埋点追踪（VIEW ➔ ENGAGE ➔ ACTION ➔ COMPLETE）、断点热点流失率统计、用户情感反馈与主动 Nudge 告警，支持高阶改进目标自主闭环。参见 [deployment_funnel/_ARCH.md](deployment_funnel/_ARCH.md)。 |
| stream_metrics/ | 流式调用按最终结果计量核心套件：杜绝中间 chunk 计数污染、按终态结果（SUCCESS/ERROR/CANCELLED/TIMEOUT）归因、TTFT 首字时延度量与防虚高膨胀统计。参见 [stream_metrics/_ARCH.md](stream_metrics/_ARCH.md)。 |
| otel_degrade/ | OpenTelemetry 缺失时优雅降级与可观测探针零硬依赖套件：缺失依赖或禁用时自动静默降级为 No-Op 空操作，保障业务执行 100% 顺畅。参见 [otel_degrade/_ARCH.md](otel_degrade/_ARCH.md)。 |
| diagnostic_stream/ | run-stream 协议诊断事件分离与正常消息流解耦套件：双轨物理隔离正轨用户消息与旁路诊断告警，提供 ACP 会话 Hook 与多维分类统计。参见 [diagnostic_stream/_ARCH.md](diagnostic_stream/_ARCH.md)。 |
| turn_usage/ | 回合级 Billed Usage 双计数核心架构：绝对累加账单（summed_with）与最新缓存状态（merged_with）严格解耦，支持自适应格式回写。参见 [turn_usage/_ARCH.md](turn_usage/_ARCH.md)。 |
| context_breakdown/ | 上下文用量七分类精准解析与 60%/90% 警戒线判定核心架构：识别真实注入标签，消除余量黑盒，支持估算与提供商实报并列对比。参见 [context_breakdown/_ARCH.md](context_breakdown/_ARCH.md)。 |
| local_sink/ | OpenTelemetry 缺失降级与 Opt-in 本地盘兜底落盘引擎：支持本地离线/沙箱环境 JSONL 落盘与定长环形内存回放，零主业务中断风险。参见 [local_sink/_ARCH.md](local_sink/_ARCH.md)。 |
| rate_limit_split/ | 限流来源拆分与失败归因套件：429 按自身限流 (myrm) 与上游拒绝 (upstream) 拆分，失败按模型厂商 (provider) 打标，未打标总数严格保持不变。参见 [rate_limit_split/_ARCH.md](rate_limit_split/_ARCH.md)。 |
| enterprise_credit_cockpit/ | 企业用量与风险运营驾驶舱引擎：统一企业 Credit 池跨端治理、人-时-数-险同链路审计留痕与穿透式治理大盘。参见 [enterprise_credit_cockpit/_ARCH.md](enterprise_credit_cockpit/_ARCH.md)。 |
| unattended_reliability/ | 无人值守可靠性三联自证套件：量化与自证重启续跑率、重复执行零副作用率与阻塞如实上报率，杜绝幻觉伪成功，支持一键复现验收跑分。参见 [unattended_reliability/_ARCH.md](unattended_reliability/_ARCH.md)。 |
| agent_insights/ | 自定义智能体运行洞察套件：面向 Agent 视角的意图与场景聚类分布、技能调用健康与耗时漏斗、以及 HITL 卡点率与 Token 产出比分析。参见 [agent_insights/_ARCH.md](agent_insights/_ARCH.md)。 |
| evidence_cross_verification/ | 多源证据交叉验证与四分制置信度根因排查套件：静态代码、分布式 Trace、运行时日志与知识库历史四维立体现证，四分制置信度推导与行动派修复补丁交付。参见 [evidence_cross_verification/_ARCH.md](evidence_cross_verification/_ARCH.md)。 |
| composite_usage_ledger/ | 基于六维复合主键的任务级与模型级持久化分摊账本与双轨对账套件：细粒度 task 归因、本地阶梯价估算与供应商回传账单双轨核算与偏差告警。参见 [composite_usage_ledger/_ARCH.md](composite_usage_ledger/_ARCH.md)。 |
| ambient_auxiliary_accounting/ | 环境感知式辅助用量正交归因上下文与功能模块独立账本套件：主干对话与后台辅助（视觉/压缩/起名/审查）正交隔离记账，保护主干会话 Prompt Cache 纯度。参见 [ambient_auxiliary_accounting/_ARCH.md](ambient_auxiliary_accounting/_ARCH.md)。 |
| multimodal_trace/ | 多模态 Trace 媒体对象引用解耦与三步排查套件：二进制媒体对象轻量元数据引用、4态可见性生命周期、OTel GenAI 多模态标准规范对齐与黄金样本加星锁。参见 [multimodal_trace/_ARCH.md](multimodal_trace/_ARCH.md)。 |
| sandbox_hardware_telemetry/ | 多维度沙箱硬件资源动态遥测与三级阶梯式失控死循环自动熔断器套件：CPU/RAM/Disk/Network 秒级度量采样、三级阶梯自愈拦截 (80% 预警 ➔ 90% 挂起 ➔ 95% 硬熔断) 与现场事故历史。参见 [sandbox_hardware_telemetry/_ARCH.md](sandbox_hardware_telemetry/_ARCH.md)。 |
| event_causality_lineage/ | 事件驱动全链路因果溯源时间线、动作归因图谱与审计白盒透视套件：外部触发事件 (GitHub/Slack/MCP/Cron) ➔ 规则匹配 ➔ Agent动作决策 ➔ 产出Diff全链路DAG，与毫秒级反向文件变更归因追溯。参见 [event_causality_lineage/_ARCH.md](event_causality_lineage/_ARCH.md)。 |
| visual_flight_recorder/ | 智能体视觉故障黑匣子录制器与卡顿状态短循环切片回放套件：滚动 15 秒 (5fps/75帧) 低开销环形内存缓冲、异常卡顿自动截断切片生成与带时间轴微动图胶卷。参见 [visual_flight_recorder/_ARCH.md](visual_flight_recorder/_ARCH.md)。 |
| dual_domain_metering/ | 双域透明计量边界界定、平台交互与沙箱执行穿透式成本核算套件：管控网关域与沙箱执行域边界明确划分、大模型Token/沙箱算力/第三方工具三维穿透核算与SHA-256防篡改财务对账凭证。参见 [dual_domain_metering/_ARCH.md](dual_domain_metering/_ARCH.md)。 |
| cross_period_milestone/ | 多智能体跨周期透视报表、多维用量核算与游戏化人效进阶里程碑套件：周/月/季度周期报表、按专属智能体堆叠拆分、环比上期增幅与经验值等级勋章体系。参见 [cross_period_milestone/_ARCH.md](cross_period_milestone/_ARCH.md)。 |
| cardinality_cap/ | 热点路径指标基数封顶与溢出桶治理套件：动态参数规整、单指标标签基数上限约束（如256）、溢出桶归并与防内存爆炸守护。参见 [cardinality_cap/_ARCH.md](cardinality_cap/_ARCH.md)。 |
| code_freshness/ | 运行时代码新鲜度三态判定维与防恒真式测试套件：进程生命周期 vs 磁盘源码 mtime 比对、热部署旧代码静默执行侦测、不可判定原因显式表达与量级哨兵自证。参见 [code_freshness/_ARCH.md](code_freshness/_ARCH.md)。 |
| runtime_zombie_reaper/ | 智能体因果树拓扑驾驶舱、父子孤儿进程自动回收、死锁轮询主动熔断与跨 Profile 资源大盘套件：PGID 进程树追踪、孤儿辅助进程级联强杀、死亡子代理死锁中断与失败任务回溯流。参见 [runtime_zombie_reaper/_ARCH.md](runtime_zombie_reaper/_ARCH.md)。 |
| delegation_billing/ | 外部委托用量计费口径透明化套件：双形态 TokenUsage 事件适配、订阅委托 vs API 计费双轨分流、用户订阅节省额度估算与跨会话委托账本大盘。参见 [delegation_billing/_ARCH.md](delegation_billing/_ARCH.md)。 |
| audit_theater/ | 用户面审计剧场与数据访问台账套件：对话内动作时间线、文件/记忆/MCP/网络四维资源访问台账、后端权威事件真实对账与撒谎免疫 SHA-256 签名。参见 [audit_theater/_ARCH.md](audit_theater/_ARCH.md)。 |
| memory_backend_metrics/ | 记忆操作与细粒度召回阶段的多后端维度标签套件：支持 memories_backend opt-in 标签控制、分后端 P50/P95 延迟对比、成功率与降级预警。参见 [memory_backend_metrics/_ARCH.md](memory_backend_metrics/_ARCH.md)。 |
| aborted_usage_ledger/ | 中止辅助模型调用账本套件：中止或异常无用量返回时强制记为 usage-unknown，严禁全零 token 伪免费，聚合时隔离已知消耗并暴露潜在财务风险。参见 [aborted_usage_ledger/_ARCH.md](aborted_usage_ledger/_ARCH.md)。 |
| active_skill_telemetry/ | 活跃技能 Span 遥测处理器套件：ContextVar 绑定当前活跃技能，自动向下游全链路 Span 注入 myrm.skill.active 属性，按技能聚合 P95 耗时与故障归因。参见 [active_skill_telemetry/_ARCH.md](active_skill_telemetry/_ARCH.md)。 |
| durable_budget_ledger/ | 持久化每日预算账本套件：从持久账本恢复当日用量，防止重试/回退/删消息导致已发生成本消失低估预算，对账会话实际账单。参见 [durable_budget_ledger/_ARCH.md](durable_budget_ledger/_ARCH.md)。 |
## Key Dependencies

- `toolkits` (via diagnostics probes)
