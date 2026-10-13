# Agent UI Subsystem Architecture (`_ARCH.md`)

## 1. 模块定位与职责
本子包位于 `src/myrm_agent_harness/agent/ui/`，实现“基于传输无关抽象的通用 ExtensionUIContext 与双向反向 Push 子协议交互引擎” (`TransportAgnosticUIContextAndReversePushSubProtocol`)。
直击工具与插件弹窗交互在 WebUI、Desktop、RPC 与无界面定时任务下的行为割裂痛点：
- **统一能力契约**：抽象统一的 `ExtensionUIContext` 标准表面，提供 `select`, `confirm`, `input`, `editor`, `notify` 五大核心交互原语；
- **传输无关兑现**：
  - `HeadlessUIContext`：无头环境（Cron、CI、批处理）确定性安全策略降级，绝不挂起进程；
  - `ReversePushUIContext`：面向 RPC、WebSocket、SSE 的双向反向 Push 交互驱动，基于 UUID 与 `asyncio.Future` 实现安全挂起、客户端握手与超时/取消熔断。

## 2. 核心文件与契约
| 文件 | 职责与能力 | 核心契约 |
| :--- | :--- | :--- |
| `ui_types.py` | 定义 `UIRequest`、`UIResponse`、`UISelectOption` 及异常类型契约 | 强类型 dataclass，零 `Any` |
| `base_ui_context.py` | `ExtensionUIContext` 抽象基类，规范五大异步交互方法 | 纯抽象接口，无具体传输依赖 |
| `headless_ui_context.py` | 无头优雅降级驱动，返回默认值与首项安全选项 | 绝不挂起，确定性返回 |
| `reverse_push_ui_context.py` | 双向反向 Push 交互驱动，带 UUID 生成、Future 挂起与超时取消 | 支持异步 push_sink 回调与 resolve_response 握手 |
| `__init__.py` | 子包公共门面导出 | 导出核心类与类型 |

## 3. 设计原则与红线
1. **单一职责与行数红线**：每个文件严格受控在 `< 300 行`；
2. **严格类型安全**：零 `Any` 类型，全面采用 Type Hints；
3. **框架与业务解耦**：Harness 层仅提供传输无关契约与核心状态驱动，不反向依赖具体的 HTTP 路由或前端组件。
