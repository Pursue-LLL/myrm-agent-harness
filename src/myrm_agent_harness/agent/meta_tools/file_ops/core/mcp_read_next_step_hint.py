"""One-shot MCP workflow reminder appended after batch-read of function docs.

[INPUT]
- /mcp/*.md 函数文档批量读取结果

[OUTPUT]
- 追加到上下文的 MCP 下一步操作提示（限定工具选择与调用顺序）

[POS]
Progressive-disclosure aid: after the agent batch-reads MCP function docs, this
reminder enforces a single constrained ``bash_code_execute_tool`` call that
awaits every needed MCP function and emits exactly one ``[RESULT]``.
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read import path_base

_MCP_DOC_PREFIX = "/mcp/"
_MCP_DOC_SUFFIX = ".md"

_MCP_NEXT_STEP_HINT = """
---
[MCP NEXT STEP] Function docs loaded. Your **next** tool call MUST be **one** `bash_code_execute_tool`:
1. `await` every MCP function still needed — in the **same** Python script (serial or `asyncio.gather`)
2. If every return structure is documented: end stdout with **exactly one** `[RESULT]` — do **not** `[OBSERVATION]` a known-value intermediate return
3. If any return structure is NOT documented: FIRST print it as `[OBSERVATION]` to confirm its real shape, then end stdout. Do **not** guess the structure. The next bash composes the final call from the observed shape.
4. Parameter names/types **only** from the docs above; if you need another function, `file_read_tool` its doc first (do not guess)
---
""".strip()


def is_mcp_function_doc_batch(paths: list[str]) -> bool:
    """True when every path is a virtual MCP function doc (batch-read before PTC bash)."""
    if not paths:
        return False
    for raw in paths:
        base = path_base(raw)
        if not base.startswith(_MCP_DOC_PREFIX) or not base.endswith(_MCP_DOC_SUFFIX):
            return False
    return True


def append_mcp_docs_next_step_hint(text: str, paths: list[str]) -> str:
    """Append workflow reminder when a batch-read covered only MCP function docs."""
    if not is_mcp_function_doc_batch(paths):
        return text
    if _MCP_NEXT_STEP_HINT in text:
        return text
    if not text.strip():
        return _MCP_NEXT_STEP_HINT
    return f"{text.rstrip()}\n\n{_MCP_NEXT_STEP_HINT}"
