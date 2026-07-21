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
使用该工具执行 Shell 命令或 Python 代码。调用时必须填写 ``reason``（≥10 字，说明执行目的）。严禁假设和猜测。

## 能力

1. **Shell**: 安全命令（git/npm/curl 等；危险/RCE 会被拦截）。
2. **脚本**: ``python script.py`` / ``bash script.sh``。
3. **Python 源码**: 直接将 Python 作为 ``command`` 传入（文件模式执行，禁止 ``python -c``）。
   - 库: pandas, numpy, scipy, matplotlib, json, datetime, re 等。
   - **PTC**: ``import myrm_tools`` — 同一次 Python 脚本内对已 bind 工具多次 RPC；函数名/参数与 Agent tool schema 一致。单次任务仍用 native tool，勿为单次任务写 PTC。PTC-only 示例: ``myrm_tools.session_store(key=..., value=...)``（非穷举）。
   - 技能: ``skills.*_skill``。

## 优先 native tool（禁止 bash 替代）

- 文件读写编辑: ``file_read_tool`` / ``file_write_tool`` / ``file_edit_tool``（禁止 echo/cat/sed/tee）。
- 搜索: ``glob_tool`` / ``grep_tool``（禁止 bash find/grep 递归）。

本工具适用于: mv/cp、包管理、构建测试、git、Python 数据处理、技能调用。

## Python vs Shell

- 短代码: 直接传入 ``command``。
- 长代码 (20+ 行): ``file_write_tool`` 写 ``*.py`` 再 ``python script.py``。

## 规则

- 路径: 优先 ``/workspace/...``；框架会 rewrite 到真实工作目录。
- Python 每次独立进程（无跨调用变量）；跨调用用 ``myrm_tools.session_store`` / ``session_load(key=...)``。
- Bash 会话按 chat 持久（环境/ cwd 保持）。
- 合并多步前确认返回值结构具体；未知结构先 ``print(f"[OBSERVATION] {x}")``，已知结果 ``print(f"[RESULT] {x}")``。
- 禁止注释、调试 print、``python -c``。

## 后台任务（可选）

``run_in_background=true`` 立即返回 pid；配合 ``bash_process_tool(action='list'|'output'|'kill')``。进度: ``echo 'MYRM_PROGRESS {"percent":42,"message":"..."}'`` 或 ``MYRM_CHECKPOINT``。
""".strip()

__all__ = ["TOOL_DESCRIPTION"]
