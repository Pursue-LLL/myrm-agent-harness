"""Bash code execution tool description (prompt visible to the LLM).

Decoupled from ``bash_code_execute_tool.py`` to keep the tool factory focused on wiring
and to satisfy the file-size guideline (single file ≤ 500 lines).

[INPUT]
- (none)

[OUTPUT]
- TOOL_DESCRIPTION: Static description string injected into the LangChain tool.

[POS]
Prompt content displayed to the LLM. Defines the contract for calling
``bash_code_execute_tool``: capabilities, accepted code shapes, output format,
and prohibitions.
"""

TOOL_DESCRIPTION = """
使用该工具执行准确安全的 Shell 命令或 Python 代码。调用时必须填写 ``reason``（≥10 字，说明执行目的）。严禁任何假设和猜测!

## 能力

1. **Shell 命令**:执行安全 shell 命令(ls/grep/curl/git 等,禁止危险命令和直接 RCE)。
2. **执行脚本**:运行已存在的脚本文件(python script.py / bash script.sh)。
3. **执行 Python 代码**:**直接将 Python 源码作为 command 传入,框架自动识别并以 file 模式执行**。
   - 可调用预装库:pandas, numpy, scipy, matplotlib, seaborn, json, datetime, re。
   - **MCP/内置批量脚本**:同一次 Python 脚本内多次调用已注册技能或内置工具,用 ``from skills.xxx_skill import ...`` 或 ``from tools.xxx import ...``;中间结果留脚本内存,最终 ``[RESULT]`` 一行。**单次调用仍用 native tool,勿为单次任务写脚本。**
   - **不要**使用 ``python -c "..."`` / ``python3 -c "..."`` 包装器 — shell 转义易破坏引号;直接传 Python 源码,框架 auto-detect + file-mode。

## 优先使用专用工具

- 读/写/编辑文件:**必须**使用 ``file_read_tool`` / ``file_write_tool`` / ``file_edit_tool``,**不要**用 echo/cat/sed/awk/tee/perl。
- 检索代码:**必须**使用 ``glob_tool`` / ``grep_tool``,**不要**用 bash 的 find/grep 递归扫描。
- 浏览目录:**必须**使用 ``glob_tool``(如 ``pattern="*"`` 或 ``pattern="**/*"``),**不要**用 bash ``ls/find``。

bash_code_execute_tool 适用于:文件移动/复制(mv/cp)、包管理、构建测试、git 操作、Python 数据处理、技能/MCP 批量脚本。

## 何时用 Python vs Shell

- **简单代码**:直接传入(无需包装、无需写文件)。
- **复杂代码**(20+ 行、需复用):先用 ``file_write_tool`` 创建 ``*.py`` 脚本,再用本工具 ``python script.py`` 运行。

## 跨 bash 调用的持久化

- **Python**:每次执行独立进程,变量/import/函数**不保持**。
- 跨多次 bash 调用持久化中间数据:在 Python 中使用 ``from tools.session_store import session_store`` / ``session_load`` / ``session_keys``(须走 ``tools.*`` import,触发 MCP IPC)。
- **Bash**:持久化会话(按 chat_id 隔离),环境变量/工作目录/Shell 函数**保持**。

## 编写原则

- 只输出回答用户所需数据,节省 token。
- 大数据文件(CSV/JSON/日志)优先用 Python 分析,只输出摘要。
- 异步:``async def main(): ...`` + ``asyncio.run(main())``,或直接 top-level ``await``。
- 路径优先写 ``/workspace/...``(sandbox cwd 默认 ``/workspace``)。

## 严格禁止

- 禁止写注释(节省 token)。
- 严禁假设、猜测返回值结构;结构未知时用 ``[OBSERVATION]`` 观察后再合并。
- 禁止调试代码、乱用 print。
- **禁止** ``import myrm_tools`` — 该命名空间仅 Dynamic Workflow 内部使用,普通对话不可用。

## 输出格式(仅允许以下两种)

- ``print(f"[OBSERVATION] {变量}")`` — 观察未知返回值结构。
- ``print(f"[RESULT] {结果}")`` — 输出最终结果。

## 后台长任务(可选)

启动 dev server / 监听器 / 长爬虫时,传 ``run_in_background=true``,立即返回 ``{pid, status}`` 而不阻塞当前轮。后台进程按 chat session 隔离,每会话最多 5 个并发。配套工具:

- ``bash_process_tool(action='list')`` — 列出本会话所有后台任务;含 ``pid / command / status / uptime_seconds / exit_code / error_category / last_progress``。
- ``bash_process_tool(action='output', pid, since_cursor?, filter?)`` — 拉 stdout/stderr 尾部;``since_cursor`` 增量轮询;``filter`` 可选行级 regex。
- ``bash_process_tool(action='wait', pid, timeout_seconds?)`` — 阻塞至退出或超时(默认 30s,最大 120s)。
- ``bash_process_tool(action='kill', pid, force?)`` — ``force=false`` SIGTERM;卡住再 ``force=true`` SIGKILL。
- ``bash_process_tool(action='write_stdin', pid, data=...)`` — 向 stdin 写原始字节(不追加换行)。
- ``bash_process_tool(action='submit_stdin', pid, data=...)`` — 向 stdin 写数据并追加 Enter(用于 y/n 等交互);GUI 也可应答。
- ``bash_process_tool(action='close_stdin', pid)`` — 发送 EOF。

### 零 token 进度上报

后台脚本 ``echo 'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}'``(或 ``{"current": 3, "total": 10}``),前端 ActivityCard 自动显示进度。检查点用 ``MYRM_CHECKPOINT {"message": "..."}``。
""".strip()

__all__ = ["TOOL_DESCRIPTION"]
