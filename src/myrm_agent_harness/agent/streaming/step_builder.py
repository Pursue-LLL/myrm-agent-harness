"""步骤数据构建器

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]

[OUTPUT]
- StepBuildResult: 步骤构建结果类型（TypedDict）
- build_step_data(): 根据工具类型构建展示数据，支持多种工具格式（搜索、网页、技能、代码等）

[POS]
Agent step data builder. Constructs frontend display data from tool names and arguments with per-tool-type customization.

"""

import json
from typing import TypedDict


class StepBuildResult(TypedDict, total=False):
    """步骤构建结果"""

    step_key: str | None  # 自定义 step_key（覆盖默认的 tool_name_tool）
    data: list[dict[str, str]]  # 展示数据


_STEP_KEY_OVERRIDES: dict[str, str] = {
    "file_read_tool": "file_read_tool",
    "file_write_tool": "file_write_tool",
    "file_edit_tool": "file_edit_tool",
    "bash_code_execute_tool": "bash_code_execute_tool_tool",
}


def get_step_key(tool_name: str) -> str:
    """从 tool_name 推导 step_key，与 build_step_data 保持一致"""
    return _STEP_KEY_OVERRIDES.get(tool_name, f"{tool_name}_tool")


def build_step_data(tool_name: str, tool_args: dict[str, object]) -> StepBuildResult:
    """根据工具类型构建展示数据

    不同工具返回不同格式：
    - 搜索类工具: [{"query": "..."}]
    - 网页获取类: [{"url": "..."}]
    - 技能选择: [{"skill_name": "...", "reason": "..."}]
    - 文件编辑器 view: [{"file_path": "..."}]
    - 代码执行: [{"code": "..."}]
    - 其他工具: [{"text": "..."}]

    Returns:
        StepBuildResult: 包含可选的 step_key 覆盖和 data 列表
    """
    # 搜索类工具 - 显示搜索查询
    if "search" in tool_name.lower():
        query = tool_args.get("questions") or tool_args.get("query") or tool_args.get("queries") or tool_args.get("q")
        if query:
            if isinstance(query, list):
                return {"data": [{"query": q} for q in query[:5]]}
            return {"data": [{"query": str(query)}]}

    # 网页获取类工具 - 显示 URL
    if any(kw in tool_name.lower() for kw in ["fetch", "webpage", "browse", "visit"]):
        url = tool_args.get("url") or tool_args.get("urls")
        if url:
            if isinstance(url, list):
                return {"data": [{"url": u} for u in url[:5]]}
            return {"data": [{"url": str(url)}]}

    # 技能选择工具 - 返回结构化的技能数据
    if tool_name == "skill_select_tool":
        skill_names = tool_args.get("skill_names", [])
        reason = str(tool_args.get("reason", ""))
        if isinstance(skill_names, list) and skill_names:
            return {"data": [{"skill_name": str(name), "reason": reason} for name in skill_names]}

    # 文件读取工具
    if tool_name == "file_read_tool":
        paths = tool_args.get("paths", [])
        # 处理 paths 可能是 JSON 字符串的情况
        if isinstance(paths, str):
            try:
                paths = json.loads(paths)
            except json.JSONDecodeError:
                # 如果解析失败，可能是单个路径
                paths = [paths] if paths else []
        if paths and isinstance(paths, list):
            import os

            items = []
            for p in paths[:10]:
                item = {"file_path": str(p), "action_type": "read"}
                try:
                    if os.path.exists(str(p)) and os.path.isfile(str(p)):
                        item["size_bytes"] = str(os.path.getsize(str(p)))
                except Exception:
                    pass
                items.append(item)
            return {"step_key": "file_read_tool", "data": items}

    # 文件写入工具
    if tool_name == "file_write_tool":
        path = tool_args.get("path", "")
        if path:
            import os

            item = {"file_path": str(path), "action_type": "write"}
            try:
                if os.path.exists(str(path)) and os.path.isfile(str(path)):
                    item["size_bytes"] = str(os.path.getsize(str(path)))
            except Exception:
                pass
            return {"step_key": "file_write_tool", "data": [item]}
        return {"data": []}

    # 文件编辑工具
    if tool_name == "file_edit_tool":
        path = tool_args.get("path", "")
        if path:
            import os

            item = {"file_path": str(path), "action_type": "write"}
            try:
                if os.path.exists(str(path)) and os.path.isfile(str(path)):
                    item["size_bytes"] = str(os.path.getsize(str(path)))
            except Exception:
                pass
            return {"step_key": "file_edit_tool", "data": [item]}
        return {"data": []}

    # bash_code_execute_tool - 返回完整代码内容
    if tool_name == "bash_code_execute_tool":
        code = tool_args.get("command", "")
        if code:
            # 返回完整代码，让前端处理展开/收起
            return {"step_key": "bash_code_execute_tool_tool", "data": [{"code": str(code)}]}

    # 其他文件/代码执行类 - 显示关键参数
    if any(kw in tool_name.lower() for kw in ["file", "code", "execute", "shell"]):
        path = tool_args.get("path") or tool_args.get("file_path")
        code = tool_args.get("code") or tool_args.get("command")
        start_line = tool_args.get("start_line")
        end_line = tool_args.get("end_line")
        if path:
            import os

            item = {"file_path": str(path)}

            # 注入 action_type
            action_type = "read"
            if any(kw in tool_name.lower() for kw in ["write", "edit", "replace", "append"]):
                action_type = "write"
            elif any(kw in tool_name.lower() for kw in ["list", "glob", "search", "find", "grep"]):
                action_type = "search"
            item["action_type"] = action_type

            # 注入 size_bytes (如果文件存在且可访问)
            try:
                if os.path.exists(str(path)) and os.path.isfile(str(path)):
                    item["size_bytes"] = str(os.path.getsize(str(path)))
            except Exception:
                pass

            if start_line is not None and end_line is not None:
                item["line_range"] = f"{start_line}-{end_line}"
            elif start_line is not None:
                item["line_range"] = f"{start_line}-"
            return {"data": [item]}
        if code:
            snippet = str(code)[:100] + ("..." if len(str(code)) > 100 else "")
            return {"data": [{"text": f" {snippet}"}]}

    # 其他工具 - 显示简要参数摘要（排除 reason，因为它会作为独立字段发送）
    if tool_args:
        summary_parts = []
        for key, value in list(tool_args.items())[:3]:
            # 跳过 reason 字段，因为它会单独显示
            if key == "reason":
                continue
            val_str = str(value)[:50] + ("..." if len(str(value)) > 50 else "")
            summary_parts.append(f"{key}: {val_str}")
        if summary_parts:
            return {"data": [{"text": " | ".join(summary_parts)}]}

    return {"data": []}
