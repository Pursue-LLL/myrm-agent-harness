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
使用该工具执行准确的 Shell 命令或 Python 代码来解决用户问题。严禁任何假设和猜测!

## 能力

1. **Shell 命令**:执行 shell 命令(mv/cp/rm、包管理、构建测试、git、curl 等)。
2. **执行脚本**:运行已存在的脚本文件(python script.py / bash script.sh)。
3. **执行 Python 代码**:**直接将 Python 源码作为 command 传入,框架自动识别并以文件模式执行**。
   - 预装三方库:pandas, numpy, scipy, matplotlib, seaborn;Python 标准库(json, datetime, re 等)均可用。
   - 可调用内置工具(`from tools.* import ...`),如 `from tools.session_store import session_store` / `session_load` / `session_keys`(均为 async,必须 await)。
   - **不要**使用 `python -c "..."` / `python3 -c "..."` 包装器 — shell 转义易破坏引号与多行字符串。直接传 Python 源码作为 command 即可。
4. **组合调用能力或方法以提效**: 根据任务依赖性分析,单次组合调用多个工具或方法以提高效率。

## 优先使用专用工具

- 读/写/编辑文件:**必须**使用 `file_read_tool` / `file_write_tool` / `file_edit_tool`,**不要**用 echo/cat/sed/awk/tee/perl 操作文件。
- 检索代码:**必须**使用 `glob_tool` / `grep_tool`,**不要**用 bash 的 find/grep 递归扫描。
- 浏览目录:**必须**使用 `glob_tool`（浅层用 `pattern="*"`;递归用 `pattern="**/*"` 时尽量配合 `path` 收窄范围），**不要**用 bash `ls/find`。

bash_code_execute_tool 适用于:文件移动/复制(mv/cp)、包管理、构建测试、git 操作、Python 数据处理、技能调用。

## 编写原则

### 准确性优先,同时考虑效率

合并多个任务可提高效率,但**前提是要使用的目标工具或方法的返回值结构都是具体的**。必须对任务做【依赖性分析】，绝对禁止假设返回值结构，否则因为强行组合未知返回值的方法而导致报错多次重试反而会降低效率，浪费token。
流程:先判定返回值是否具体 → 具体则合并到一次执行 → 不具体则先 `[OBSERVATION]` 探路。

#### 返回值具体性判定

- **判定标准**:「具体」的唯一标准:**文档中明确写出每个字段的名称和类型**且能转换为 TS 类型代码,仅说「返回字典/列表」**不算**具体!
- **引用类型展开**:**引用类型必须展开到基本类型**:dict 列出所有 key 名和 value 类型,list 说明元素类型。
- **具体示例**:`{"code": str}` / `list[{"id": int}]` / `"yyyy-mm-dd 字符串"`。
- **模糊示例(必须阻断)**:`返回xx字典` / `返回JSON` / `结果是车站信息列表`。

#### 返回值具体 → 合并到一次代码执行(无依赖用 gather 并行,有依赖串行)

以查票工具为例:若已知 `fetch_date()` 与 `fetch_codes()` 的具体返回值,且 `fetch_date()` 与 `fetch_codes()` 没有依赖关系,但 `query_tickets(date, from_station, to_station)` 依赖于前两个工具的返回值,则先并行执行 `fetch_date()` 与 `fetch_codes()`,再串行执行 `query_tickets(...)`:

```python
import asyncio
date, codes = await asyncio.gather(fetch_date(), fetch_codes())
tickets = await query_tickets(date=date, from_station=codes["from"], to_station=codes["to"])
print(f"[RESULT] {tickets}")
```

#### 返回值不具体 → 先 OBSERVATION,下次再合并

若 `fetch_date()` 与 `fetch_codes()` 的返回值结构不具体,则先输出 `[OBSERVATION]`,下次观察返回值结构后再决定下次如何编写:

```python
import asyncio
date, codes = await asyncio.gather(fetch_date(), fetch_codes())
print(f"[OBSERVATION] date={date}, codes={codes}")
```

### 优化策略

- 用代码控制流(while/if/try)替代多次工具调用。
- 只输出回答用户所需数据,节省 token。
- 大数据文件(CSV/JSON/日志)优先用 Python 分析,只输出摘要。

### 异步写法

`async def main(): ...` + `asyncio.run(main())`,或直接 top-level `await`(框架已支持)。

### 路径

- 命令与 Python 代码中的路径优先写 ``/workspace/...``(默认工作目录)。

### Python 无状态,Bash 持久化

- **Python**:每次执行独立进程,变量/import/函数**不保持**。如需跨调用持久化数据,使用 `from tools.session_store import session_store` / `session_load` / `session_keys`(均为 async,必须 await)。
- **Bash**:持久化会话(按 chat_id 隔离),环境变量/工作目录/Shell 函数**保持**。

## 严格禁止

- 禁止写注释(一次性脚本无需注释,节省 token)。
- 严禁假设、猜测返回值结构。
- 禁止调试代码、乱用 print。
- 禁止 `import myrm_tools`(在此环境不可用,会被拦截)。

## 输出格式(仅允许以下两种)

- `print(f"[OBSERVATION] {变量}")` — 观察未知返回值结构。
- `print(f"[RESULT] {结果}")` — 输出最终结果。

## 后台长任务(可选)

启动 dev server / 监听器 / 长爬虫时,传 `run_in_background=true`,立即返回 `{pid, status}` 而不阻塞当前轮。后台进程按 chat session 隔离,每会话最多 5 个并发。配套工具:

- `bash_process_tool(action='list')` — 列出本会话所有后台任务;含 `pid / command / status / uptime_seconds / exit_code` 等字段;若上报过进度则含 `last_progress`,便于比对哪个 worker 卡住、哪个快收尾。
- `bash_process_tool(action='output', pid, since_cursor?, filter?)` — 拉 stdout/stderr 尾部;传上次的 ``next_cursor`` 作为 ``since_cursor`` 实现增量轮询;``filter`` 为可选行级 regex。
- `bash_process_tool(action='wait', pid, timeout_seconds?)` — 阻塞至进程退出或超时(默认 30s,最大 120s);超时则任务仍在运行。
- `bash_process_tool(action='kill', pid, force?)` — `force=false` 正常终止;仍存活则 `force=true` 强制结束。
- `bash_process_tool(action='write_stdin', pid, data=...)` — 向 stdin 写原始字节(不追加换行)。
- `bash_process_tool(action='submit_stdin', pid, data=...)` — 向 stdin 写数据并追加 Enter(用于 y/n 等交互提示);也可由 GUI 应答。
- `bash_process_tool(action='close_stdin', pid)` — 向 stdin 发送 EOF,关闭交互输入。

### 零 token 进度上报

后台脚本若 `echo 'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}'`(或 `{"current": 3, "total": 10}`),自动显示进度条,无需 LLM 参与。检查点用 `MYRM_CHECKPOINT {"message": "..."}`。三方工具的自然输出(如 `Building 42%`、`3/10 tests`、`Compiling main.rs`)也会被启发式识别。
""".strip()

__all__ = ["TOOL_DESCRIPTION"]
