"""Bash code execution tool description (prompt visible to the LLM).

Decoupled from ``bash_code_execute_tool.py`` to keep the tool factory focused on wiring
and to satisfy the file-size guideline (single file ≤ 500 lines).

[INPUT]
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- DEFAULT_BASH_TOOL_DESCRIPTION_LOCALE: Default English locale constant ("en")
- TOOL_DESCRIPTION_EN: English tool description SSOT
- TOOL_DESCRIPTION_ZH: Chinese tool description SSOT
- TOOL_DESCRIPTION: Backward compatibility alias to Chinese description
- resolve_bash_code_execute_tool_description(): Locale-aware resolver

[POS]
Prompt content displayed to the LLM. Defines the contract for calling
``bash_code_execute_tool``: capabilities, merge/OBSERVATION rules, native-tool routing,
background job stdin/eviction hints, output format, and prohibitions.
"""

from __future__ import annotations

from typing import Final

from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_BASH_TOOL_DESCRIPTION_LOCALE: Final[str] = "en"

TOOL_DESCRIPTION_ZH: Final[str] = """
使用该工具执行准确的 Shell 命令或 Python 代码来高效精准地解决用户问题。严禁任何假设和猜测!

## 能力

1. **Shell 命令**:执行 shell 命令(mv/cp/rm、包管理、构建测试、git、curl 等)。
2. **执行脚本**:运行已存在的脚本文件(python script.py / bash script.sh)。
3. **执行 Python 代码**:**直接将 Python 源码作为 command 传入**（支持原生多行代码，无需压缩或转义）。
   - 预装三方库:pandas, numpy, scipy, matplotlib, seaborn;Python 标准库(json, datetime, re 等)均可用。
   - **不要**使用 `python -c "..."` / `python3 -c "..."` 包装器 — shell 转义易破坏引号与多行字符串。直接传原生 Python 源码作为 command 即可。
4. **组合执行提效(管道思想)**: 单次调用内串联多步 — ① Python 源码(gather/串行/控制流,含技能批量); ② Shell 用 `&&`/`|` 串联,或执行已有脚本(见 #2)。返回值具体才可接管道,否则先 `[OBSERVATION]` — 细则见「编写原则」。

## 优先使用专用工具

- 读/写/编辑:**必须**用 `file_read_tool` / `file_write_tool` / `file_edit_tool`,**不要** echo/cat/sed/awk/tee/perl。
- 找文件/搜内容/列目录:**必须**用 `glob_tool` / `grep_tool`,**不要** bash `find/grep/ls` 递归扫描。参数与示例见各工具描述。

bash_code_execute_tool 适用于:系统/运行时操作(mv/cp/rm、包管理、构建测试、git、curl)、Python/脚本/技能调用、后台长任务(见下) — 读文件/搜内容/列目录用上节专用工具。

## 编写原则

### 准确性优先,同时考虑效率

合并多个任务可提高效率,但**前提是要使用的目标工具或方法的返回值结构都是具体的**。必须对任务做【依赖性分析】，绝对禁止假设返回值结构，否则因为强行组合未知返回值的方法而导致报错多次重试反而会降低效率，浪费token。
流程:先判定返回值是否具体 → 具体则合并到一次执行 → 不具体则先 `[OBSERVATION]` 探路。

#### 返回值具体性判定

- **判定标准**:「具体」的唯一标准:**文档中明确写出每个字段的名称和类型**(能直接索引取值),仅说「返回字典/列表」**不算**具体!
- **引用类型展开**:**引用类型必须展开到基本类型**:dict 列出所有 key 名和 value 类型,list 说明元素类型。
- **具体示例**:`{"code": str}` / `list[{"id": int}]` / `"yyyy-mm-dd 字符串"`。
- **模糊示例(必须阻断)**:`返回xx字典` / `返回JSON` / `结果是车站信息列表`。

#### 返回值具体 → 合并到一次代码执行(无依赖用 gather 并行,有依赖串行)

以查票工具为例:若已知 `fetch_date()` 与 `fetch_codes()` 的具体返回值,且 `fetch_date()` 与 `fetch_codes()` 没有依赖关系,但 `query_tickets(date, from_station, to_station)` 依赖于前两个工具的返回值,则先并行执行 `fetch_date()` 与 `fetch_codes()`,再串行执行 `query_tickets(...)`:

```python
import asyncio

async def main():
    date, codes = await asyncio.gather(fetch_date(), fetch_codes())
    tickets = await query_tickets(date=date, from_station=codes["from"], to_station=codes["to"])
    print(f"[RESULT] {tickets}")

asyncio.run(main())
```

#### 返回值不具体 → 先 OBSERVATION,下次再合并

若 `fetch_date()` 与 `fetch_codes()` 的返回值结构不具体,则先输出 `[OBSERVATION]`,下次观察返回值结构后再决定下次如何编写:

```python
import asyncio

async def main():
    date, codes = await asyncio.gather(fetch_date(), fetch_codes())
    print(f"[OBSERVATION] date={date}, codes={codes}")

asyncio.run(main())
```

### 优化策略

- 依赖关系和返回值结构清晰明确时，将多次操作合并进一次 Python 源码,用 while/if/try 控制流完成循环/条件/异常,避免多次往返调用。
- 只输出所需数据:大数据(CSV/JSON/日志)用 Python 分析,只给摘要。
- 超大输出 eviction 截断时,按返回路径用 ``file_read_tool`` 读 ``.context/.../evicted/``。
- 命令失败时,先读 stdout/stderr/错误提示定位根因再修复,勿盲目重试同一命令（严禁在未调整参数或逻辑时连续重复执行同一失败操作）。

### 异步写法

技能/MCP 调用为 async — 必须 await。统一使用 `async def main(): ...` + `asyncio.run(main())` 入口(写法见上方示例)。

### 路径

- 命令与 Python 代码中的路径优先写 ``/workspace/...``(默认工作目录)。

### Python 无状态,Bash 持久化

- **Python**:每次执行独立进程,变量/import/函数**不保持**。**优先合并到单次代码执行中**;确需跨轮持久化 → 写 ``/workspace/...`` 中间 JSON(``json.dump/load`` 或 ``file_write_tool``);**禁止**大 payload 进 ``[RESULT]``/``[OBSERVATION]``。
- **Bash**:当前会话跨轮持久保持(按 chat session 隔离),环境变量/工作目录/Shell 函数**始终生效**。

## 严格禁止

- 严禁添加非必要的解释性注释，只输出纯净可执行代码。
- 严禁盲目假设未知返回值结构，遇到未知数据必须先通过 `[OBSERVATION]` 探测。
- 严禁输出多余的无意义 print，标准输出严格仅允许 `[OBSERVATION]` 与 `[RESULT]`。

## 输出格式(仅允许以下两种)

- `print(f"[OBSERVATION] {变量}")` — 观察未知返回值结构。
- `print(f"[RESULT] {结果}")` — 输出最终结果（仅输出下游决策所需的关键字段或摘要，禁止 dump 超大无用原始对象）。

## 后台长任务(可选)

启动 dev server / 监听器 / 长爬虫时,传 `run_in_background=true`,立即返回 `{pid, status}` 而不阻塞当前轮。后台进程按 chat session 隔离,每会话最多 5 个并发。

**注意**:传 `run_in_background=true` 时**不要**在命令末尾追加 `&` — 工具已自动后台化,追加 `&` 会导致进程脱离管理(pid 失效,无法 output/kill/wait)。

配套工具 `bash_process_tool` 提供 7 个 action:list(会话内全部任务,含 `last_progress`) / output(增量轮询:传上次 `next_cursor` 为 `since_cursor`) / wait / kill / write_stdin / submit_stdin / close_stdin — 参数与规则详见其工具描述。

**关键**:output/wait 返回 `waiting_for_input=true` 时,读 `input_wait_hint` 并用 `submit_stdin` 应答,勿盲轮询;`waiting_for_input=false` 时正常拉输出/等待即可。

### 零 token 进度上报

后台脚本若 `echo 'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}'`(或 `{"current": 3, "total": 10}`),自动显示进度条,无需 LLM 参与。检查点用 `MYRM_CHECKPOINT {"message": "..."}`。三方工具的自然输出(如 `Building 42%`、`3/10 tests`、`Compiling main.rs`)也会被启发式识别。
""".strip()

TOOL_DESCRIPTION_EN: Final[str] = """
Execute Shell commands or Python code to solve problems accurately and efficiently. Do NOT make assumptions or guesses!

## Capabilities

1. **Shell commands**: Execute shell commands (mv/cp/rm, package management, build & test, git, curl, etc.).
2. **Execute scripts**: Run existing script files (`python script.py` / `bash script.sh`).
3. **Execute Python code**: **Pass Python source code directly as `command`** (supports raw multi-line scripts without escaping or compression).
   - Pre-installed libraries: pandas, numpy, scipy, matplotlib, seaborn; Python standard library (json, datetime, re, etc.) are available.
   - **Do NOT** wrap with `python -c "..."` — shell escaping can break quotes and multi-line strings. Pass raw Python code directly as `command`.
4. **Combined execution (pipelining)**: Chain multiple steps in a single call:
   - ① Python source (asyncio.gather / sequential / control flow, including skill batching);
   - ② Shell chaining with `&&`/`|`, or running existing scripts (see #2).
   - Only pipeline when return structures are concrete; otherwise use `[OBSERVATION]` first (see "Principles").

## Prefer Dedicated Tools

- Read / Write / Edit: **MUST** use `file_read_tool` / `file_write_tool` / `file_edit_tool`. Do **NOT** use echo/cat/sed/awk/tee/perl.
- Find files / search content / list dirs: **MUST** use `glob_tool` / `grep_tool`. Do **NOT** use bash `find/grep/ls` recursively.

`bash_code_execute_tool` is for: system/runtime operations (mv/cp/rm, build, test, git, curl), Python/script execution, and background tasks.

## Principles

### Accuracy First, Efficiency Second

Combining multiple tasks improves efficiency, but **only when the return value structure of target methods is concrete**. Always analyze dependencies. NEVER guess return structures.

1. **Concrete return value**: Field names and types are explicitly documented (e.g., `{"code": str}`, `list[{"id": int}]`).
2. **Ambiguous return value**: Only says "returns dict" or "JSON result" without field breakdown → must emit `[OBSERVATION]` first to inspect.

#### Concrete structure → Combine into one Python execution:
```python
import asyncio

async def main():
    date, codes = await asyncio.gather(fetch_date(), fetch_codes())
    tickets = await query_tickets(date=date, from_station=codes["from"], to_station=codes["to"])
    print(f"[RESULT] {tickets}")

asyncio.run(main())
```

#### Ambiguous structure → Output OBSERVATION first, combine next turn:
```python
import asyncio

async def main():
    date, codes = await asyncio.gather(fetch_date(), fetch_codes())
    print(f"[OBSERVATION] date={date}, codes={codes}")

asyncio.run(main())
```

### Optimization Strategies

- When dependencies and return structures are clear, combine multiple steps into one Python script with while/if/try control flow to avoid multiple tool roundtrips.
- Output only necessary data: analyze large data (CSV/JSON/logs) in Python and print only summaries.
- When large output is evicted/truncated, read the returned path under `.context/.../evicted/` using `file_read_tool`.
- When a command fails, read stdout/stderr and error messages to identify the root cause before fixing. Do not blindly retry the same failed command (never repeat identical failed operations without adjusting arguments or logic).

### Async Patterns
Skill/async invocations must be awaited. Use `async def main(): ...` + `asyncio.run(main())` entrypoint.

### Paths
Prefer `/workspace/...` (default working directory) in commands and Python code.

### Python is Stateless, Bash is Persistent
- **Python**: Each execution runs in an independent process; variables and imports do not persist. **Prefer combining operations into a single execution**; for cross-turn persistence, write intermediate JSON under `/workspace/...` (`json.dump/load` or `file_write_tool`). Never put large payloads into `[RESULT]` or `[OBSERVATION]`.
- **Bash**: Persistent across turns within the current session (isolated per chat session); environment variables, working directory, and shell functions remain active.

## Prohibitions
- Do NOT add unnecessary explanatory comments; output clean, executable code only.
- NEVER assume unknown return structures; always inspect unfamiliar data with `[OBSERVATION]` first.
- Do NOT emit superfluous print statements; stdout is strictly restricted to `[OBSERVATION]` and `[RESULT]`.

## Output Format (Only two allowed)
- `print(f"[OBSERVATION] {variable}")` — Inspect unknown return value structures.
- `print(f"[RESULT] {result}")` — Output final results (print only essential fields/summaries for downstream decisions; avoid dumping giant raw objects).

## Background Tasks (Optional)
For dev servers, watchers, or long-running jobs, pass `run_in_background=true` to return `{pid, status}` immediately without blocking. Max 5 concurrent jobs per session.
**Note**: Do NOT append `&` at the end of the command when `run_in_background=true` (the tool handles backgrounding automatically).
Use `bash_process_tool` to manage background jobs: `list` (includes `last_progress`), `output` (incremental tail with `since_cursor`), `wait`, `kill`, `write_stdin`, `submit_stdin`, `close_stdin`.
When output/wait returns `waiting_for_input=true`, check `input_wait_hint` and respond using `submit_stdin`.

### Progress Reporting
Background scripts can emit `echo 'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}'` (or `{"current": 3, "total": 10}`) to automatically update UI progress bars without LLM turns. Use `MYRM_CHECKPOINT {"message": "..."}` for checkpoints.
""".strip()

# Backward-compatible alias for existing imports expecting Chinese constant
TOOL_DESCRIPTION: Final[str] = TOOL_DESCRIPTION_ZH


def resolve_bash_code_execute_tool_description(
    locale: str | None = DEFAULT_BASH_TOOL_DESCRIPTION_LOCALE,
) -> str:
    """Resolve LLM-facing bash_code_execute_tool description based on locale.

    Defaults to English when locale is omitted or non-Chinese.
    """
    if is_chinese(locale):
        return TOOL_DESCRIPTION_ZH
    return TOOL_DESCRIPTION_EN


__all__ = [
    "DEFAULT_BASH_TOOL_DESCRIPTION_LOCALE",
    "TOOL_DESCRIPTION",
    "TOOL_DESCRIPTION_EN",
    "TOOL_DESCRIPTION_ZH",
    "resolve_bash_code_execute_tool_description",
]
