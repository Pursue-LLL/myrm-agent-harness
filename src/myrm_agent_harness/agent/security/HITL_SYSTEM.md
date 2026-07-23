# Human-in-the-Loop审批系统 - 技术文档

## 概述

基于LangGraph `interrupt()` 的统一Human-in-the-Loop审批系统，支持Web和IM双渠道，具备批量审批、重启安全和持久化白名单能力。

---

## 核心特性

### 1. 统一Interrupt机制
所有审批流程使用LangGraph原生`interrupt()`，确保：
- ✅ 重启安全（Checkpointer持久化状态）
- ✅ 标准化（符合LangChain HITL规范）
- ✅ 双渠道一致性（Web + IM共享同一逻辑）

### 2. 工具纠错与断点续传 (Tool-Error Clarification)
复用上述底层通道，当长链条任务中的任一工具抛出 `ToolClarificationException` 时，不再让大模型盲目重试，而是直接抛出 `action_type="tool_clarification"` 的挂起事件。
**用户体验**：
- 前端会弹出 JSON/文本表单卡片，明确告知错误原因（如：“查无此人”）。
- 用户补齐正确参数后，流程直接唤醒挂起的工具节点，带着最新参数无损恢复（Resume）并执行。
- 保证了极高的长任务链可靠性，且不污染 Prompt History 缓存。

### 3. 批量审批
当Agent单轮调用多个需审批工具时，系统自动合并为一次`interrupt()`，用户一次性决策所有工具。

**实现机制**（after_model hook）：
- 使用`ToolApprovalMiddleware.aafter_model()`拦截AIMessage
- 在工具执行前批量评估所有`tool_calls`
- 分类为：auto_approved、auto_denied、pending_approval
- 对pending_approval列表一次性调用`interrupt()`（同步）
- Resume时按顺序处理decisions数组，修改AIMessage.tool_calls

**用户体验**：
- 单工具：1次interrupt → 1次决策
- 3个工具：1次interrupt → 1次决策（而非3次打断）

### 3. 持久化 Allowlist
"Always Allow" 决策存储到数据库（`user_tool_allowlist` 表），跨重启、跨会话持久有效。

**四级粒度**（`AllowlistEntry`）：permission → tool → exact（args hash）→ **pattern**（shell glob，`command_pattern` 列）。

**Pattern 规则**（`command_allowlist_pattern.py`）：单段命令推导 `{token0} {token1} *`；复合 shell（`&&`/`|`/`;`）永不写入、永不命中；DENY 仍优先于 allowlist。

**缓存机制**：
- Lazy-load（首次访问时从DB加载）
- Per-user lock（并发安全）
- TTL refresh（默认5分钟，确保多实例一致性）
- Opportunistic cleanup（ttl_seconds > 0时回收过期缓存）

---

## 数据结构

### InboundMessage扩展
```python
@dataclass(frozen=True, slots=True)
class InboundMessage:
    channel: str
    sender_id: str
    content: str
    resume_value: dict[str, object] | None = None  # Resume决策
    # ... other fields ...
```

### Interrupt Payload（LangChain标准）
```python
interrupt({
    "actionRequests": [  # 支持多工具
        {
            "action": "tool_name",
            "args": {...},
            "description": "reason",
            "command_spans": [{"startIndex": 0, "endIndex": 3}],  # optional, shell tools
            "command_span_risks": ["safe", "unknown"],  # parallel to command_spans
            "command_span_reasons": ["safe", "unknown_command"]  # parallel i18n reason codes
        }
    ],
    "reviewConfigs": [
        {"allowedDecisions": ["approve", "reject", "edit"]}
    ],
    "extensions": {
        "timeout": {"seconds": 300, "expiresAt": timestamp, "behavior": "deny"},
        "workspaceRoot": "/path/to/workspace",  # optional, shell approval context
        "approval": {
            "requestId": uuid,
            "sessionKey": "channel:chat_id",
            "batchSize": 3  # 批量时添加
        }
    }
})
```

### Resume Response（LangChain标准）
```python
{
    "decisions": [  # 数组，支持批量
        {
            "type": "approve" | "reject" | "edit",
            "args": {...},  # optional, for edit
            "feedback": "...",  # optional, for reject
            "extensions": {
                "allowAlways": bool | {"tool": bool, "args"?: bool, "pattern"?: bool}
            }
        }
    ]
}
```

### Shell 审批 Edit 安全门禁
用户 edit 决策修改 shell 命令时，harness 在 `apply_approval_decisions` 中二次调用 `classify_command_risk`：
- 命令文本未变 → 允许
- 变更后仍为 SAFE → 允许（如 `rm -rf /` → `ls`）
- 变更后为非 SAFE → 拒绝 edit，返回 ToolMessage，需 Agent 重新发起审批

### 无 UI 通道的自治上下文自动拒绝
以下执行上下文没有前端审批通道，遇到 ASK 决策时 `ToolApprovalMiddleware` 自动 deny，防止死锁：
- **Subagent**：`is_subagent=True` 且无 `subagent_task_id`
- **Shadow Agent**：`is_shadow_agent=True`（后台 idle 任务经 `restricted_shadow_context()` 设置）

Shadow Agent 场景由 `agent/background_worker/shadow_context.py` 提供执行层舱壁：封死 Python/Bash 执行，写操作仅限技能边车路径。

---

## Web渠道流程

### 审批请求
```
Agent执行 → interrupt() → GraphInterrupt → SSE stream结束
→ Frontend收到tool_approval_request事件
→ 弹出ToolApprovalDialog（展示所有tools，支持批量分组；shell 工具展示终端命令 + pipeline span 高亮）
```

### 用户决策
```
用户操作UI（批量：收集所有决策） → 构造resume_value
→ POST /api/chat/agent-stream with resume_value
→ ChannelAgentExecutor: Command(resume=resume_value)
→ interrupt()返回decisions → 各工具执行或拒绝
```

---

## IM渠道流程

### 消息处理主流程
```
平台 → AgentRouter._consume_loop() → _handle_merged()
  → _prepare_execution_context(): 身份解析 + session 检查 + topic 验证；返回 `_RouterExecutionContext`（`router_models.py` 冻结类型），含策略变换后的执行用 InboundMessage（群聊：前缀剥离、context_messages 等）
  → _execute_prepared_context(): 注册 `_active_tasks`（asyncio.Task、CancellationToken、channel、chat_id、placeholder_id）+ `_setup_message_effects` + `_consume_executor_stream`（`router_stream.RouterStreamMixin`）+ `_deliver_agent_result`；`finally` 中 `_cleanup_effects`（当 `_approval_msg_ids` 中有 pending approval 时保留 `_active_tasks` 条目，确保数字快捷回复如 "1" 能被正确识别为审批命令）；占位符 id 写入 `_AgentTurnScratch`（`router_models.py`）供 `_handle_merged` 外层异常路径
```

- `RouterStreamMixin` / `RouterCommandsMixin` 所需宿主实例字段由 `routing/router_host.py` 中的 `RouterStreamHost`、`RouterCommandsHost`（`typing.Protocol`）描述。
- 流式占位符编辑间隔：`routing/router_constants.py` 中 `_MIN_PROGRESS_INTERVAL`、`_MIN_STREAM_INTERVAL`；是否跳过单次编辑由 `routing/router_stream_throttle.py` 中 `should_skip_throttled_placeholder_edit` 判定（`RouterStreamMixin._try_throttled_edit` 使用）。
- 会话级映射键（活跃任务、审批 message_id、`SessionGate.gate_key` 等）：`routing/router_keys.py` 的 `routing_session_key`（`channel` + peer；与按 `message_id` 的去重键不同）。
- 入站带语音附件时，`_handle_merged` 先 `transcribe_inbound` 再 `_prepare_execution_context`。
- 外层异常路径的 `send_error_reply` 使用 `exec_for_error`（转写成功后与 STT 后的 `msg` 一致，`prepare` 成功后为 `ctx.exec_msg`）；`SessionGate.on_task_complete` 使用 `finally` 中的 `msg`，键为 `gate_key(msg)`。

### 审批请求
```
Agent执行 → interrupt() → GraphInterrupt → stream结束
→ ProgressUpdate(quick_replies) 经 Router 发送为独立消息
→ _approval_msg_ids[session_key] 记录该审批消息的 message_id（用于后续编辑状态文案）
→ _consume_executor_stream 检测 has_pending_approval，丢弃最终 OutboundMessage（避免在用户审批前发送中间结果）
```

### 用户决策（单工具与批量）
```
快捷回复或文本：/approve、/deny、1、2；批量：/batch a,d,a（与 parse_approval_command 一致）
→ Router._handle_approval_command()
→ 单条：resume_value = {"decisions": [{"type": "approve"|"reject"}]}；批量：decisions 与待审工具顺序一一对应
→ InboundMessage(resume_value=..., metadata 含 is_resume=True) 重新进入 SessionGate
```

### Resume处理流程
```
execute_stream()检测is_resume=True
→ 正常执行身份解析和topic解析
→ _load_history_without_persist()（不持久化resume命令）
→ Command(resume=resume_value) → Agent继续执行
```

---

## 批量审批实现

### Backend（middlewares/approval/）

使用`aafter_model` hook实现批量审批，按单一职责原则拆分为4个方法：

```python
class ToolApprovalMiddleware(AgentMiddleware):
    async def aafter_model(self, state, runtime):
        """主流程协调（92行）"""
        # 1. 获取context并加载allowlist
        config, last_ai_msg, session_key, user_id = ...
        
        # 2. 评估所有tool_calls
        auto_approved, auto_denied, pending = await self._evaluate_tool_batch(
            last_ai_msg.tool_calls, config, allowlist, is_cron, user_id, ...
        )
        
        # 3. 构建payload并interrupt
        if pending:
            payload, indices = self._build_interrupt_payload(pending, session_key)
            batch_response = interrupt(payload)
            
            # 4. 应用决策
            revised_calls, messages = await self._apply_approval_decisions(
                batch_response["decisions"], last_ai_msg, auto_denied, pending, indices, user_id
            )
        
        return {"messages": [last_ai_msg, *messages]}
    
    async def _evaluate_tool_batch(...):
        """5层安全评估+分类（109行）"""
        # YOLO快速路径→Capability→Shell Analyzer→Path Policy→Permission Rules→Allowlist
    
    def _build_interrupt_payload(...):
        """构造LangChain标准payload（63行）"""
        # actionRequests + reviewConfigs + extensions
    
    async def _apply_approval_decisions(...):
        """应用决策+allowlist更新+审计（93行）"""
        # approve→保留tool_call / edit→修改args / reject→ToolMessage(error)
```

**设计特性**：
- 在工具执行前统一拦截（after_model时机）
- 同步调用`interrupt()`，确保异常正确传播
- 每个方法职责单一，符合SRP原则

### Frontend（ToolApprovalDialog.tsx）

**自动分组**：
```typescript
// 按batchId分组
const { batchGroups, singleRequests } = useMemo(() => {
    const batches: Map<string, ToolApprovalRequest[]> = new Map();
    const singles: ToolApprovalRequest[] = [];
    
    for (const req of queue) {
        if (req.batchId) {
            const group = batches.get(req.batchId) || [];
            group.push(req);
            batches.set(req.batchId, group);
        } else {
            singles.push(req);
        }
    }
    
    return { batchGroups, singleRequests };
}, [queue]);
```

**决策收集**：
```typescript
// 批量：收集所有决策后统一提交
const sortedRequests = batchRequests.sort((a, b) => 
    (a.batchIndex ?? 0) - (b.batchIndex ?? 0)
);
const decisions = sortedRequests.map((r) => {
    const dec = newDecisions.get(r.requestId)!;
    return {
        type: dec.type,
        args: dec.extra?.edited_args,
        feedback: dec.extra?.feedback,
        extensions: { allowAlways: dec.extra?.allow_always ?? false }
    };
});

const resumeValue = { decisions };
```

---

## 安全特性

### 5层权限评估
1. **PathPolicy** - 文件路径限制
2. **NetworkPolicy** - 域名白名单
3. **CapabilityFence** - 能力声明
4. **TaintTracking** - 数据流污染检测
5. **ToolApproval** - 人类审批

### 工具级AST安全门禁
`browser_execute_script_tool` 在脚本执行前进行AST静态分析，检测绕过域名过滤/HITL守卫的特权API：
- `page.request.*` (bypasses context.route())
- `page.evaluate()` / `page.evaluate_handle()` (bypasses enforce_js_eval_guard)
- `page.context` / `page.new_page()` / `page.new_context()` (unprotected context access)

命中时触发独立 `interrupt(action_type="script_privileged_api")`，用户可审查脚本内容后批准或拒绝。

### 三态决策模型
- **APPROVE**: 原样执行
- **EDIT**: 修改参数后执行
- **REJECT**: 拒绝并返回反馈给Agent

### Anti-retry机制
累计拒绝3次后，在ToolMessage中注入提示：
```
[System: 3 tool calls denied in this session. 
Do NOT retry denied tools. Explain to the user what you wanted to do 
and ask for permission or alternative instructions.]
```

### 速率限制
防止恶意用户发起大量审批请求（配置在`approval_rate_limiter.py`）。

---

## 代码位置

| 组件 | 文件路径 |
|------|---------|
| 核心中间件 | `myrm_agent_harness/agent/middlewares/approval/` |
| Allowlist管理 | `myrm_agent_harness/agent/security/approval_flow.py` |
| 权限评估引擎 | `myrm_agent_harness/agent/security/engine.py` |
| IM渠道路由 | `app/channels/routing/router.py` |
| Channel执行器 | `app/core/channel_bridge/agent_executor.py` |
| Frontend UI | `myrm-agent-frontend/src/components/features/chat-window/approval/AllowAlwaysConfirmDialog.tsx` + `AllowlistSection.tsx` |
| DB持久化 | `app/database/allowlist_store.py` |

---

## 测试覆盖

| 测试类型 | 文件 | 覆盖范围 |
|---------|------|---------|
| Allowlist 单元 | `tests/agent/security/test_approval_flow.py` | permission / pattern glob `check()` |
| Pattern 推导 | `tests/agent/security/test_command_allowlist_pattern.py` | 复合检测、glob 匹配、parity 向量 |
| Middleware pattern | `tests/agent/middlewares/test_approval_edge_cases.py` | pattern 存入、`evaluate_tool_batch` auto-approve |
| Allowlist REST | `myrm-agent/.../tests/api/security/test_allowlist_api.py` | list/delete `granularity=pattern` |
| LIVE Chrome E2E | `myrm-agent/.../tests/e2e/test_allowlist_pattern_live_chrome_e2e.py` | 真实模型 bash → pattern → Settings |
| SHPOIB attach replay | `myrm-agent/.../tests/api/agent/test_shpoib_hitl_attach_replay.py` | collector replay + hitl-probe（无 LLM） |
| Allowlist 并发 | `tests/agent/security/test_approval_flow_coverage.py` | 并发 / TTL / store 协议 |
| DB 持久化 | `myrm-agent/.../app/database/allowlist_store.py` + server 集成测 | `command_pattern` 列 UNIQUE |

---

## 系统能力总结

当前系统提供：
- ✅ 统一interrupt()机制（重启安全）
- ✅ 批量审批（Web + IM双渠道，多工具一次决策）
- ✅ 持久化Allowlist（跨重启有效）
- ✅ 双渠道完整支持（Web UI + IM批量命令）
- ✅ 完整安全防护（5层评估 + 审计日志）
- ✅ 审批超时三层守卫（前端倒计时 + 后端 WebUI 调度器 + 后端 Channel 调度器）
- ✅ 超时行为可配置（deny/allow），超时决策记录安全审计日志
- ✅ Hook 系统支持 HTTP webhook + auth 认证
- ✅ 生产级代码质量（类型安全、测试与静态检查）

**IM批量审批命令**：
```
/batch a,d,a     # 批准、拒绝、批准（3个工具）
/batch approve,reject,approve  # 等价完整写法
```

系统已达到**生产可用状态**，核心功能完整，架构清晰优雅。
