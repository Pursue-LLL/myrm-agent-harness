# Tool Management System Design

> Agent 工具注册、分层、去重、排序与生命周期管理 SSOT。控制 LLM 动作空间复杂度（ASCS）与 token 预算。

---

## 设计目标

1. **减少动作空间**：工具越少 → 决策越准（见 ASCS 指标）
2. **三层分级**：CORE / COMMON / EXTENDED — profile 可开关 COMMON/EXTENDED
3. **统一注册**：替代 BaseAgent 内 scattered dedup/sort
4. **框架 vs 业务边界**：harness 只放通用原语；SaaS 集成走 skill/MCP/server

---

## 系统架构

```
SkillAgent / Server factory
        ↓
tool_layers.py — CORE/COMMON/EXTENDED SSOT
        ↓
registry.py — dedup + sort + ToolBindMode (TURN1 / DISCOVERABLE / RUNTIME_ONLY)
        ↓
lifecycle_manager.py — init_tools / cleanup_tools
        ↓
action_space.py — ASCS _profiler
```

---

## 核心文件

| 文件 | 职责 |
|------|------|
| `tool_layers.py` | 三层优先级注册表；未注册工具 WARNING |
| `registry.py` | 去重、排序、`ToolBindMode` 三分绑定 |
| `lifecycle_manager.py` | 工具 init/cleanup 编排 |
| `lifecycle_protocol.py` | `LifecycleAwareTool` Protocol |
| `action_space.py` | ActionSpaceProfiler / ASCS |
| `types.py` | `ToolBindMode` + 子系统类型 |
| `TOOL_DESIGN_STRATEGY.md` | 设计策略与竞品对比 |
| `DEFAULT_AGENT_TOKEN_INVENTORY.md` | tiktoken 逐项计量 |

---

## 与 meta_tools / toolkits 边界

| 层 | 路径 | 职责 |
|----|------|------|
| 注册 SSOT | `tool_management/` | 谁在哪个 layer、token 计量 |
| 框架元工具 | `meta_tools/` | Agent 绑定工具实现 |
| 通用工具 | `toolkits/` | 可独立 import 的原语 |

Server `_tool_layer_bootstrap.py` 扩展 EXTENDED 层业务工具。

---

## CI 集成

```bash
python scripts/validate_tool_registry.py          # 注册一致性
python scripts/validate_tool_registry.py --generate-docs  # 刷新 TOOL_COUNT 块
```

---

## 扩展指南

1. 新 harness 工具 → `register_tool_layer()` + meta_tools 或 toolkits 实现
2. 更新 token inventory（`python scripts/measure_turn1_token_inventory.py` + 同步 `DEFAULT_AGENT_TOKEN_INVENTORY.md`）
3. 运行 validate_tool_registry

控制面工具（不进默认 bind）taxonomy 见 `DEFAULT_AGENT_TOKEN_INVENTORY.md` §4.18。

---

## ToolBindMode 绑定契约

`ToolBindMode`（`types.py`）三分绑定语义如下：

| 模式 | Turn1 schema | discover_capability 索引 | 执行池（ToolNode / dynamic resolve） |
|------|--------------|--------------------------|--------------------------------------|
| `TURN1` | ✅ 绑定 | ❌ | ❌（已在 Turn1） |
| `DISCOVERABLE` | ❌ | ✅ | ✅（AutoMount 后） |
| `RUNTIME_ONLY` | ❌ | ❌ | ✅（中间件注入，用户无感） |

**API 契约**（`registry.py`）：

- `resolve()` — 仅返回 `TURN1` 工具（LLM 首回合可见 schema）
- `get_discoverable_tools()` — 仅 `DISCOVERABLE`（discover 搜索 + AutoMount 候选）
- `get_runtime_tools()` — `DISCOVERABLE` + `RUNTIME_ONLY`（延迟执行与中间件钩子）

**典型映射**：

- MCP aggregate overflow、bash 后台进程、skill_analyze/discovery、cron、browser_local_search → `DISCOVERABLE`
- `_completion_check`（CompletionGuard）→ `RUNTIME_ONLY`（名称 `_` 前缀自动推断）

**禁止**：`get_deferred_tools()` 已删除；新代码不得混用 `deferred_tools` 变量名，统一使用 `discoverable_tools`（构造参数）与上述三个 registry 方法。

**GUI 暴露**（`emit_tools_snapshot`）：仅序列化 `TURN1` 工具，与 `resolve()` 一致；`DISCOVERABLE` / `RUNTIME_ONLY` 不进 `tools_snapshot` SSE。

---

## 参考资料

- [tool_management/_ARCH.md](_ARCH.md)
- [TOOL_DESIGN_STRATEGY.md](TOOL_DESIGN_STRATEGY.md)
- [meta_tools/META_TOOLS_SYSTEM.md](../meta_tools/META_TOOLS_SYSTEM.md)
