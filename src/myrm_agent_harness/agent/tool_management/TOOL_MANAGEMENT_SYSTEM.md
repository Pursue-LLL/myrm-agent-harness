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
registry.py — dedup + sort + deferred tools
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
| `registry.py` | 去重、排序、deferred tool 支持 |
| `lifecycle_manager.py` | 工具 init/cleanup 编排 |
| `lifecycle_protocol.py` | `LifecycleAwareTool` Protocol |
| `action_space.py` | ActionSpaceProfiler / ASCS |
| `types.py` | 子系统类型定义 |
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
2. 更新 token inventory（tiktoken cl100k_base 实测）
3. 运行 validate_tool_registry

---

## 参考资料

- [tool_management/_ARCH.md](_ARCH.md)
- [TOOL_DESIGN_STRATEGY.md](TOOL_DESIGN_STRATEGY.md)
- [meta_tools/META_TOOLS_SYSTEM.md](../meta_tools/META_TOOLS_SYSTEM.md)
