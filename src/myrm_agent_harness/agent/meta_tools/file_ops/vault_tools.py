"""Vault Tools

提供共享工件金库（Artifact Vault）的存取工具。
允许子智能体将超大文本/JSON/报告存入 Vault，向主智能体返回一个指针 `vault://<uuid>`，避免打爆上下文限制。
主智能体可以通过指针直接向前端下发，或用提取工具读取局部内容。

[INPUT]
- agent.artifacts.vault::ArtifactVault (POS: Shared Artifact Vault)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- VaultPutInput: class — Vault Put Input
- VaultGetInput: Retrieve content from a Shared Artifact Vault pointer (va...
- VaultExtractInput: Extract specific lines from a massive Shared Artifact Vau...
- vault_put_tool: function — vault_put_tool
- vault_get_tool: function — vault_get_tool

[POS]
Vault Tools
"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


def _get_workspace_root() -> str | None:
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver
    try:
        return str(WorkspacePathResolver.resolve_workspace_root())
    except Exception as e:
        logger.error(f"Failed to resolve workspace root: {e}")
        return None


class VaultPutInput(BaseModel):
    content: str = Field(description="The massive string content to store in the vault (JSON, CSV, markdown, etc.)")
    filename: str = Field(description="A descriptive filename for this artifact (e.g. 'financial_report_2026.md')")
    content_type: str = Field(default="text/plain", description="MIME type (e.g., text/csv, application/json, text/markdown)")
    description: str = Field(default="", description="Optional description of the content for other agents to understand")


@tool("vault_put_tool", args_schema=VaultPutInput)
async def vault_put_tool(content: str, filename: str, content_type: str = "text/plain", description: str = "") -> dict[str, Any]:
    """Store massive data/text into the Shared Artifact Vault and get a 'vault://' pointer back.

    CRITICAL: ALWAYS use this tool instead of outputting massive strings (e.g., generating >2000 lines of code/JSON/CSV)
    in your final answer! When you finish a heavy task as a subagent, write the result here and ONLY return the
    vault://<uuid> pointer to your parent agent. This prevents context explosion and crashing the system.
    """
    workspace_root = _get_workspace_root()
    if not workspace_root:
        return {"success": False, "error": "Workspace root not found in context. Vault is unavailable."}

    try:
        vault = ArtifactVault(workspace_root)
        pointer = vault.put(content=content, filename=filename, content_type=content_type, description=description)

        try:
            from myrm_agent_harness.agent.artifacts import (
                infer_artifact_type_from_extension,
                push_inline_artifact,
            )
            inferred_type = infer_artifact_type_from_extension(filename)
            push_inline_artifact(
                filename=filename,
                preview_url=pointer,
                artifact_type=inferred_type,
                content_type=content_type
            )
        except Exception as inner_e:
            logger.warning("Failed to push inline artifact for vault pointer %s: %s", pointer, inner_e)

        return {
            "success": True,
            "message": f"Successfully stored {len(content)} characters.",
            "vault_pointer": pointer,
            "instruction": f"CRITICAL: Include this pointer '{pointer}' in your final answer so the parent agent can access it!"
        }
    except Exception as e:
        logger.error(f"Vault Put failed: {e}")
        return {"success": False, "error": str(e)}


class VaultGetInput(BaseModel):
    vault_pointer: str = Field(description="The vault pointer URI (e.g., vault://1234-abcd-5678)")
    preview_only: bool = Field(default=True, description="If true, only returns the first 2000 chars to avoid blowing up your context.")


@tool("vault_get_tool", args_schema=VaultGetInput)
async def vault_get_tool(vault_pointer: str, preview_only: bool = True) -> dict[str, Any]:
    """Retrieve content from a Shared Artifact Vault pointer (vault://).

    If a subagent handed you a vault:// pointer, you can use this tool to peek at the content.
    WARNING: Set preview_only=False ONLY if you are absolutely sure the content is small enough to fit in your context.
    """
    workspace_root = _get_workspace_root()
    if not workspace_root:
        return {"success": False, "error": "Workspace root not found in context. Vault is unavailable."}

    try:
        vault = ArtifactVault(workspace_root)
        meta = vault.get_meta(vault_pointer)
        if not meta:
            return {"success": False, "error": f"Vault pointer not found or expired: {vault_pointer}"}

        obj_path = vault.get_object_path(vault_pointer.replace("vault://", ""))
        if not obj_path.exists():
            return {"success": False, "error": "Vault object content not found on disk"}

        if preview_only:
            with open(obj_path, "rb") as f:
                content_bytes = f.read(4000)
            content_str = content_bytes.decode("utf-8", errors="replace")
            truncated = len(content_bytes) == 4000 or len(content_str) > 2000
            if len(content_str) > 2000:
                content_str = content_str[:2000]
            if truncated:
                content_str += "\n\n...[TRUNCATED BY PREVIEW_ONLY=TRUE]..."
        else:
            content_bytes = obj_path.read_bytes()
            content_str = content_bytes.decode("utf-8", errors="replace")
            truncated = False

        return {
            "success": True,
            "metadata": meta.to_dict(),
            "content": content_str,
            "is_truncated": truncated,
        }
    except Exception as e:
        logger.error(f"Vault Get failed: {e}")
        return {"success": False, "error": str(e)}


class VaultExtractInput(BaseModel):
    vault_pointer: str = Field(description="The vault pointer URI (e.g., vault://1234-abcd-5678)")
    regex_pattern: str | None = Field(default=None, description="Optional regex pattern to match lines")
    keyword: str | None = Field(default=None, description="Optional keyword to search for (case-insensitive). Provide either keyword or regex_pattern.")
    max_lines: int = Field(default=50, description="Maximum number of matching lines to return")
    context_lines: int = Field(default=2, description="Number of context lines to include before and after each match")


@tool("vault_extract_tool", args_schema=VaultExtractInput)
async def vault_extract_tool(
    vault_pointer: str,
    regex_pattern: str | None = None,
    keyword: str | None = None,
    max_lines: int = 50,
    context_lines: int = 2,
) -> dict[str, Any]:
    """Extract specific lines from a massive Shared Artifact Vault pointer (vault://) using a keyword or regex.

    CRITICAL: Use this tool to read specific parts of a huge file instead of downloading the whole thing with vault_get_tool.
    It returns matching lines along with some surrounding context, preventing your context window from blowing up.
    """
    if not regex_pattern and not keyword:
        return {"success": False, "error": "Must provide either regex_pattern or keyword"}

    workspace_root = _get_workspace_root()
    if not workspace_root:
        return {"success": False, "error": "Workspace root not found in context. Vault is unavailable."}

    try:
        import re

        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        vault = ArtifactVault(workspace_root)
        meta = vault.get_meta(vault_pointer)
        if not meta:
            return {"success": False, "error": f"Vault pointer not found or expired: {vault_pointer}"}

        pattern = None
        if regex_pattern:
            pattern = re.compile(regex_pattern, re.IGNORECASE)
        elif keyword:
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)

        # Internal access for fast stream processing, circumventing full memory load
        obj_path = vault.get_object_path(vault_pointer.replace("vault://", ""))
        if not obj_path.exists():
            return {"success": False, "error": "Content not found on disk"}

        with open(obj_path, encoding="utf-8", errors="ignore") as f:
            from collections import deque
            buffer = deque(maxlen=context_lines)
            last_printed = -2
            print_next_n = 0
            matches_found = 0
            result_lines = []

            for i, raw_line in enumerate(f):
                line = raw_line[:4000]
                if len(raw_line) > 4000:
                    line += " ...[LINE TRUNCATED]"

                is_match = bool(pattern and pattern.search(line))

                if is_match:
                    matches_found += 1
                    # 打印前置上下文
                    for buf_i, buf_line in buffer:
                        if buf_i > last_printed:
                            if buf_i > last_printed + 1 and last_printed != -2:
                                result_lines.append("---")
                            result_lines.append(f"[{buf_i+1}] {buf_line.strip()}")
                            last_printed = buf_i

                    # 打印当前匹配行
                    if i > last_printed:
                        if i > last_printed + 1 and last_printed != -2:
                            result_lines.append("---")
                        result_lines.append(f"[{i+1}] {line.strip()}")
                        last_printed = i

                    print_next_n = context_lines
                else:
                    if print_next_n > 0:
                        if i > last_printed:
                            if i > last_printed + 1 and last_printed != -2:
                                result_lines.append("---")
                            result_lines.append(f"[{i+1}] {line.strip()}")
                            last_printed = i
                        print_next_n -= 1

                    buffer.append((i, line))

                if matches_found >= max_lines and print_next_n == 0:
                    break

        if not result_lines:
             return {"success": True, "message": f"No matches found for '{keyword or regex_pattern}'."}

        return {
            "success": True,
            "metadata": meta.to_dict(),
            "extracted_content": "\n".join(result_lines)
        }
    except Exception as e:
        logger.error(f"Vault Extract failed: {e}")
        return {"success": False, "error": str(e)}
