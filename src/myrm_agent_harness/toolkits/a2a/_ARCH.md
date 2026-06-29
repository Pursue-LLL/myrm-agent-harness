# A2A (Agent-to-Agent) Protocol Module

## 定位

Google A2A 协议的框架级基础设施，与 `acp/`（IDE↔Agent）和 `mcp/`（Agent↔Tools）并列，
构成完整的 Agent 协议栈：**ACP + MCP + A2A**。

## 职责

| 文件 | 职责 |
|------|------|
| `types.py` | A2A 数据模型（AgentCard、AgentSkill 等 Pydantic frozen model） |
| `protocols.py` | AgentCardProvider Protocol（框架-业务边界契约） |
| `resolver.py` | A2ACardResolver（通过 URL 发现第三方 AgentCard，含 SSRF 防护和 TTL 缓存） |

## 依赖关系

- `types.py` ← 无外部依赖
- `protocols.py` ← `types.py`
- `resolver.py` ← `types.py` + `httpx` + `core/security/http/secure_fetch.py`（`secure_get`）

## SSRF 边界

- 默认路径：`resolve()` 经 `secure_get` 做 DNS pin + redirect 逐跳校验。
- `skip_ssrf_check=True`：裸 httpx，**仅限 trusted internal 调用**；禁止从用户可控 URL 路径传入。

## 不做什么

- 不处理 A2A 任务调用（属于后续 Agent 动态调度模块）
- 不处理多租户（属于 control-plane 层）
- 不做 JWS 签名验证（初期不需要，Protocol 已预留扩展点）
