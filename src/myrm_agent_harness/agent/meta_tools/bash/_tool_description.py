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
and prohibitions. Keep terse to maximise prompt cache hit rate.
"""

TOOL_DESCRIPTION = """
使用该工具执行准确安全的 Shell 命令或 Python 代码来解决用户问题。严禁任何假设和猜测!

## 能力

1. **Shell 命令**:执行安全 shell 命令(ls/grep/curl/git 等,禁止危险命令和直接 RCE)。
2. **执行脚本**:运行已存在的脚本文件(python script.py / bash script.sh)。
3. **执行 Python 代码**:**直接将 Python 源码作为 command 传入,框架自动识别并以文件模式执行**。
   - 可调用预装库:pandas, numpy, scipy, matplotlib, seaborn, json, datetime, re。
   - **可 `import myrm_tools` 做 PTC**(Programmatic Tool Calling):**同一次 Python 脚本内**对已 bind 工具多次 RPC,中间结果留脚本内存,最终 `[RESULT]` 一行。函数名/参数与 Agent tool schema 一致,返回 JSON/str。**单次调用仍用 native tool,勿为单次任务写 PTC。** PTC-only 示例:`myrm_tools.session_store(key=..., value=...)`(非穷举)。
   - 可调用已注册技能(skills.*_skill)。
   - **严禁使用 `python -c "..."` / `python3 -c "..."` 包装器** — shell 转义会破坏复杂引号与多行字符串,产生不可预测的 SyntaxError。直接传代码即可,框架会自动以文件模式执行。

## 优先使用专用工具

- 读/写/编辑文件:**必须**使用 `file_read_tool` / `file_write_tool` / `file_edit_tool`,**不要**用 echo/cat/sed/awk/tee/perl 操作文件 — 缺少验证、无回滚、还会触发额外审批,浪费交互轮次。
- 检索代码:**必须**使用 `glob_tool` / `grep_tool`,**不要**用 bash 的 find/grep 递归扫描。
- 浏览目录:**必须**使用 `glob_tool`（如 `pattern="*"` 或 `pattern="**/*"` 限定 depth），**不要**用 bash `ls/find`。

bash_code_execute_tool 适用于:文件移动/复制(mv/cp)、包管理、构建测试、git 操作、Python 数据处理、技能调用。

## 何时用 Python vs Shell

- **简单代码**:直接传入(无需任何包装、无需写文件)。
- **复杂代码**(20+ 行、需复用):先用 `file_write_tool` 创建 `*.py` 脚本,再用本工具 `python script.py` 运行。

## 编写原则

### 准确性优先,绝对禁止假设返回值结构

合并多个任务可提高效率,但**前提是所有返回值结构都是具体的**。必须对任务做【依赖性分析】:

#### 返回值具体性判定

- 「具体」的唯一标准:**文档中明确写出每个字段的名称和类型**且能转换为 TS 类型代码,仅说「返回字典/列表」**不算**具体!
- **引用类型必须展开到基本类型**:dict 列出所有 key 名和 value 类型,list 说明元素类型。
- 具体:`{"code": str}` / `list[{"id": int}]` / `"yyyy-mm-dd 字符串"`。
- 模糊(必须阻断):`返回xx字典` / `返回JSON` / `结果是车站信息列表`。

#### 场景一:无依赖 -> gather 并行,合并到一次代码执行

```python
import asyncio
task_a, task_b = await asyncio.gather(func_a(), func_b())
print(f"[RESULT] a={task_a}, b={task_b}")
```

#### 场景二:有依赖且返回值结构具体 -> 合并到一次代码执行,依赖部分串行

```python
import asyncio
date, codes = await asyncio.gather(get_current_date(), get_station_code_of_citys(citys="北京|上海"))
tickets = await query_left_ticket(date=date, from_station=codes["BJP"], to_station=codes["SHH"])
print(f"[RESULT] {tickets}")
```

#### 场景三:有依赖且返回值结构不具体 -> 先 OBSERVATION,下次再合并

```python
import asyncio
date, codes = await asyncio.gather(get_current_date(), get_station_code_of_citys(citys="北京|上海"))
print(f"[OBSERVATION] date={date}, codes={codes}")
```

### 优化策略

- 用代码控制流(while/if/try)替代多次工具调用。
- 只输出回答用户所需数据,节省 token。
- 大数据文件(CSV/JSON/日志)优先用 Python 分析,只输出摘要。

### 异步写法

`async def main(): ...` + `asyncio.run(main())`,或直接 top-level `await`(框架已支持)。

### Python 无状态,Bash 持久化

- **Python**:每次执行独立进程,变量/import/函数**不保持**。如需跨调用持久化数据,使用 `myrm_tools.session_store(key=..., value=...)` / `myrm_tools.session_load(key=...)`。
- **Bash**:持久化会话(按 chat_id 隔离),环境变量/工作目录/Shell 函数**保持**。

## 严格禁止

- 禁止写注释(节省 token)。
- 严禁假设、猜测返回值结构。
- 禁止调试代码、乱用 print。
- 严禁 `python -c` / `python3 -c`(直接传源码)。

## 输出格式(仅允许以下两种)

- `print(f"[OBSERVATION] {变量}")` — 观察未知返回值结构。
- `print(f"[RESULT] {结果}")` — 输出最终结果。

## 后台长任务(可选)

启动 dev server / 监听器 / 长爬虫时,传 `run_in_background=true`,立即返回 `{pid, status}` 而不阻塞当前轮。后台进程按 chat session 隔离,每会话最多 5 个并发。配套工具:

- `bash_process_tool(action='list')` — 列出本会话所有后台任务;每条记录包含 `pid / command / status / uptime_seconds / exit_code / error_category`,任务一旦上报过进度还会带 `last_progress` (`percent / step / message / updated_at`),让你**不用为每个 pid 单独拉 output** 就能比对哪个 worker 卡住、哪个快收尾。
- `bash_process_tool(action='output', pid, since_cursor?)` — 拉 stdout/stderr 尾部;传上次的 `next_cursor` 实现增量轮询,token 极省。
- `bash_process_tool(action='kill', pid, force?)` — `force=false` 发 SIGTERM,卡住再 `force=true` 发 SIGKILL。

### 零 token 进度上报

后台脚本若 `echo 'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}'`(或 `{"current": 3, "total": 10}`),前端 ActivityCard 自动显示进度条/步骤号,完全无需 LLM 参与。检查点用 `MYRM_CHECKPOINT {"message": "..."}`。三方工具的自然输出(如 `Building 42%`、`3/10 tests`、`Compiling main.rs`)也会被启发式识别。
""".strip()

__all__ = ["TOOL_DESCRIPTION"]
