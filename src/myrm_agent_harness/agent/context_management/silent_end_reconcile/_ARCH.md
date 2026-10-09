# silent_end_reconcile Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.silent_end_reconcile`
核心职责：SSE 无终帧静默断流时服务端运行态对账套件，识别非正常终止并核对远端运行态，杜绝前端运行态假死与 loading 无法退役。

## 模块结构
| 文件 | 职责 |
|---|---|
| `silent_end_types.py` | 强类型契约、终态事件枚举、服务端保留状态、对账裁决枚举、静默断流工单与对账结果模型 |
| `stream_terminal_watchdog.py` | SSE 传输层终帧看门狗，跟踪块事件并判定 HTTP 结束时是否缺少业务终态事件 |
| `server_runtime_verifier.py` | 服务端运行态保留探针，向服务端 topic/operation 注册表核对真值并制定对账结算方案 |
| `silent_end_reconcile_suite.py` | 统一协调主门面 `TerminalMissingSilentEndServerReconcileSuite` |
| `__init__.py` | 包级公共符号门面导出 |
