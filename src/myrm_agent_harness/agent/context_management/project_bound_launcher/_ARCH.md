# project_bound_launcher Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.project_bound_launcher`
核心职责：项目绑定会话启动器与工作区上下文继承套件，破除冷启动摩擦，实现工作区目录、Git 仓库元数据及项目目标首帧上下文的确定性继承与注入。

## 模块结构
| 文件 | 职责 |
|---|---|
| `launcher_types.py` | 强类型契约、项目元数据快照、启动请求与首帧继承帧结构定义 |
| `workspace_metadata_inspector.py` | 工作目录合法性校验、Git 分支/根路径轻量元数据探测安全器 |
| `context_inheritance_assembler.py` | 项目目标/技术栈摘要与工作区环境组装器，渲染开聊首帧只读上下文结构块 |
| `project_bound_session_launcher.py` | 项目绑定会话创建器、分支会话元数据继承调度与独立快聊平滑回退器 |
| `project_bound_session_suite.py` | 统一协调门面 `ProjectBoundSessionLauncherSuite` |
| `__init__.py` | 包级公共符号门面导出 |
