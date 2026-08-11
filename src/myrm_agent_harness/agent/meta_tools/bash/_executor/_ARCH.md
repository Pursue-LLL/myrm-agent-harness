# bash/_executor/

## Overview
BashExecutor 聚合根与执行编排域：同步/后台执行、上下文构建、技能 staging、会话生命周期。

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | 域聚合出口：导出 `BashExecutor`、`BashExecutionError`。 | — |
| `executor.py` | Core | BashExecutor 聚合根（DI 编排，MRO: Execute → Background → Prepare → Context，由架构测试锁定）。 | ✅ |
| `execute_mixin.py` | Core | 同步 ``execute()`` 编排；stdout/stderr 对称 eviction；失败路径双流落盘 + ``BashExecutionError`` 携带 eviction 引用。 | ✅ |
| `background_mixin.py` | Core | ``spawn_background()`` 后台进程注册；剥离裸尾 ``&`` 防孤儿进程。 | ✅ |
| `prepare_mixin.py` | Core | MCP proxy 启动、代码类型检测、技能 staging。 | ✅ |
| `context_mixin.py` | Core | ExecutionContext 构建、OAuth issuer 作用域、事件日志。 | ✅ |
| `constants.py` | Internal | 共享常量（MCP 超时下限）。 | — |
| `workspace_manager.py` | Core | 工作区薄委托（懒加载绑定存储根）。 | ✅ |
| `skill_workspace_manager.py` | Core | 技能文件 staging 路径解析。 | ✅ |
| `mcp_citation_handler.py` | Core | MCP Metadata Extractor。 | ✅ |
| `event_logging.py` | Internal | 命令执行事件日志（脱敏+分类）。 | ✅ |
| `error.py` | Core | 结构化 ``BashExecutionError``，携带 stdout/stderr eviction 引用。 | ✅ |
| `auto_yield.py` | Core | 前台白名单命令超时自动后台化。 | ✅ |
| `command_classifier.py` | Core | 命令分类器（READ/WRITE/DANGEROUS/NETWORK/GIT/SEARCH/PYTHON/SKILL）。 | ✅ |
| `sensitive_parameter_redactor.py` | Core | 命令参数脱敏（--token/--password/--api-key 等）。 | ✅ |

## Key Dependencies

- `../_compression/output_eviction`（大输出落盘）
- `../_background`（后台任务注册表）
- `toolkits.code_execution`（执行器）
