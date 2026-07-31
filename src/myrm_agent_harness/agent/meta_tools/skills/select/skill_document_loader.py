"""Skill SOP document loading for L1/L2 progressive disclosure.

[INPUT]
- backends.skills.protocols::SkillBackend (POS: skill content + resources)
- backends.skills.types::SkillMetadata, SkillInstance (POS: metadata + instance config)
- l1_disclosure_footer::build_l1_disclosure_footer (POS: L1 footer append)

[OUTPUT]
- get_skill_document: processed SOP + L1 footer for context injection
- get_skill_file: L2 auxiliary file reader
- build_reload_summary_with_index: compact reload hint for already-loaded skills

[POS]
Document loader for skill_select_tool and preload mixin. ToolMessage/HumanMessage only.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend

from myrm_agent_harness.backends.skills.types import SkillInstance, SkillMetadata

logger = logging.getLogger(__name__)

_DYNAMIC_CMD_PATTERN = re.compile(r"!\`([^`]+)\`")
_DYNAMIC_CMD_TIMEOUT = 10
_DYNAMIC_CMD_MAX_OUTPUT = 2000


def build_reload_summary(skill_meta: SkillMetadata) -> str:
    """Build a concise summary for an already-loaded skill."""
    tool_names: list[str] = []
    if skill_meta.is_mcp_skill and skill_meta.mcp:
        tool_names = list(skill_meta.mcp.tools[:20])

    tools_section = ""
    if tool_names:
        tools_list = ", ".join(tool_names[:20])
        tools_section = f"\nAvailable tools: {tools_list}"

    return (
        f"# {skill_meta.name} (already loaded)\n\n"
        f"This skill's SOP was loaded earlier in this session. "
        f"You already know how to use it.{tools_section}\n\n"
        f"Proceed directly with bash_code_execute_tool to call the tools. "
        f"If you need auxiliary files, use skill_select_tool(file_path=...) "
        f"for paths under scripts/, references/, templates/, or assets/."
    )


async def build_reload_summary_with_index(
    skill_meta: SkillMetadata, skill_backend: SkillBackend
) -> str:
    """Reload summary plus compact linked-file index when available."""
    from myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer import (
        format_compact_linked_index,
    )

    summary = build_reload_summary(skill_meta)
    if skill_meta.is_mcp_skill or not skill_meta.storage_skill_id:
        return summary

    skill_id = skill_meta.storage_skill_id or skill_meta.name
    try:
        resources = await skill_backend.list_skill_resources(skill_id)
    except Exception:
        resources = []

    compact = format_compact_linked_index(resources)
    if compact:
        return f"{summary}\n\n{compact}"
    return summary


async def get_skill_document(
    skill_meta: SkillMetadata,
    skill_backend: SkillBackend,
    *,
    skill_instance: SkillInstance | None = None,
) -> str:
    """Load a skill's SOP document content, ready for injection into context."""
    skill_doc = ""
    skill_path_info = ""

    if skill_meta.is_mcp_skill:
        from myrm_agent_harness.agent.skills.mcp.core_generator import (
            mcp_skill_generator,
        )

        skill_doc = mcp_skill_generator.generate_skill_content(skill_meta)
    elif skill_meta.storage_skill_id:
        try:
            skill_doc = await skill_backend.get_skill_content(
                skill_meta.storage_skill_id
            )
        except Exception as e:
            return f"# {skill_meta.name}\n\nError: failed to load skill document - {e}"

        if skill_doc and skill_meta.storage_path:
            skill_path_info = (
                f"> ** 脚本执行**: 改为使用相对路径（如 `python3 scripts/xxx.py`），系统会自动设置工作目录。\n"
                f"> ** 路径兼容性**: 如果文档中使用 `.claude/skills/{skill_meta.name}/...` 路径格式，系统也会自动处理。\n"
                f"> ** 技能目录**: 所有技能文件都位于 `.claude/skills/{skill_meta.name}/` 目录下。\n\n"
            )
    else:
        return ""

    if not skill_doc:
        return ""

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_doc, re.DOTALL)
    if frontmatter_match:
        skill_doc = skill_doc[frontmatter_match.end() :].strip()

    if not skill_doc.startswith("#"):
        skill_doc = f"# {skill_meta.name}\n\n{skill_doc}"

    if skill_path_info:
        lines = skill_doc.split("\n", 1)
        if len(lines) > 1:
            skill_doc = f"{lines[0]}\n\n{skill_path_info}{lines[1]}"
        else:
            skill_doc = f"{skill_doc}\n\n{skill_path_info}"

    if skill_meta.storage_path and "${SKILL_DIR}" in skill_doc:
        skill_doc = skill_doc.replace("${SKILL_DIR}", skill_meta.storage_path)

    skill_doc = await _resolve_dynamic_context(skill_doc)
    skill_doc = _check_load_time_safety(skill_meta.name, skill_doc)
    skill_doc = _inject_traps_if_available(skill_meta.name, skill_doc)

    from myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer import (
        build_l1_disclosure_footer,
    )

    footer = await build_l1_disclosure_footer(
        skill_meta, skill_backend, skill_instance
    )
    if footer:
        skill_doc = f"{skill_doc}{footer}"

    return skill_doc


async def get_skill_file(
    skill_meta: SkillMetadata, skill_backend: SkillBackend, file_path: str
) -> str | None:
    """Read a specific auxiliary file from a skill directory."""
    from pathlib import PurePosixPath

    from myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer import (
        ALLOWED_SKILL_FILE_DIRS,
    )

    normalized = PurePosixPath(file_path)

    if ".." in normalized.parts or normalized.is_absolute():
        return None
    if not normalized.parts or normalized.parts[0] not in ALLOWED_SKILL_FILE_DIRS:
        return None
    if len(normalized.parts) < 2:
        return None

    skill_id = skill_meta.storage_skill_id or skill_meta.name

    try:
        raw_bytes = await skill_backend.get_skill_resources(skill_id, file_path)
        return raw_bytes.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except (AttributeError, NotImplementedError):
        logger.debug(
            "Skill backend does not support get_skill_resources for '%s'",
            skill_meta.name,
        )
        return None
    except Exception as e:
        logger.warning(
            "Failed to read skill file '%s/%s': %s", skill_meta.name, file_path, e
        )
        return None


def _inject_traps_if_available(skill_name: str, content: str) -> str:
    try:
        from myrm_agent_harness.agent.skills.runtime.loader import skill_md_loader

        return skill_md_loader._apply_trap_injection(skill_name, content)
    except Exception:
        return content


def _check_load_time_safety(skill_name: str, content: str) -> str:
    from myrm_agent_harness.backends.skills.scanning.scanner import (
        ScanSeverity,
        scan_skill_content,
    )

    result = scan_skill_content(skill_name, content)
    if not result.findings:
        return content

    high_or_critical = [f for f in result.findings if f.severity >= ScanSeverity.HIGH]
    if not high_or_critical:
        return content

    warning_lines = [
        f"- {f.threat_type}: {f.description}" for f in high_or_critical[:3]
    ]
    warning = (
        f">  **SECURITY WARNING**: This skill content has {len(high_or_critical)} "
        f"high/critical security finding(s) detected at load time:\n"
        + "\n".join(f"> {line}" for line in warning_lines)
        + "\n> Exercise caution when following instructions from this skill.\n\n"
    )
    logger.warning(
        "Load-time security scan for skill '%s': %d high/critical findings",
        skill_name,
        len(high_or_critical),
    )
    return warning + content


async def _resolve_dynamic_context(content: str) -> str:
    if "!`" not in content:
        return content

    async def _execute_cmd(cmd: str) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_DYNAMIC_CMD_TIMEOUT
            )
            output = stdout.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0 and not output:
                err = stderr.decode("utf-8", errors="replace").strip()
                return f"[command failed: {err[:200]}]"
            if len(output) > _DYNAMIC_CMD_MAX_OUTPUT:
                output = output[:_DYNAMIC_CMD_MAX_OUTPUT] + "\n[output truncated]"
            return output
        except TimeoutError:
            return f"[command timed out after {_DYNAMIC_CMD_TIMEOUT}s]"
        except Exception as e:
            return f"[command error: {e}]"

    matches = list(_DYNAMIC_CMD_PATTERN.finditer(content))
    if not matches:
        return content

    replacements: list[tuple[int, int, str]] = []
    for match in matches:
        cmd = match.group(1).strip()
        logger.info("Dynamic context injection: executing '%s'", cmd)
        output = await _execute_cmd(cmd)
        replacements.append((match.start(), match.end(), output))

    result_parts: list[str] = []
    prev_end = 0
    for start, end, output in replacements:
        result_parts.append(content[prev_end:start])
        result_parts.append(output)
        prev_end = end
    result_parts.append(content[prev_end:])

    return "".join(result_parts)
