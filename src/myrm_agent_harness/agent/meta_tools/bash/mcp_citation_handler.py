"""MCP Metadata Extractor

负责解析和提取 MCP 调用元数据。
 不再注册引用，只返回结构化元数据。

[INPUT]
- (none)

[OUTPUT]
- MCPMetadataExtractor: class — M C P Metadata Extractor

[POS]
MCP Metadata Extractor
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 类型别名：按技能分组的 MCP 调用数据
# 格式：{skill_name: [{"tool": tool_name, "result": result_data}, ...]}
type SkillCallsDict = dict[str, list[dict[str, str]]]


class MCPMetadataExtractor:
    """MCP 元数据提取器

     职责：
    - 从执行输出中提取 MCP 调用标记
    - 按技能分组 MCP 调用
    - 返回结构化元数据（供业务层使用）
    - 清理和格式化输出内容
    """

    # MCP 数据标记的正则模式：__MCP_DATA__{json}__END__
    _MCP_DATA_PATTERN = re.compile(r"__MCP_DATA__(.+?)__END__\n?")

    def extract_metadata(self, stdout: str) -> tuple[str, dict[str, Any]]:
        """从输出中提取 MCP 调用标记，返回清洁输出和元数据

         处理流程：
        1. 解析所有 __MCP_DATA__{json}__END__ 标记
        2. 按 MCP 服务（技能）分组
        3. 返回结构化元数据（供业务层使用）
        4. 移除原始标记，返回清洁输出

        Args:
            stdout: 原始标准输出

        Returns:
            元组：(清洁的输出, MCP 元数据字典)
        """
        if not stdout:
            return stdout, {}

        has_marker = "__MCP_DATA__" in stdout
        logger.info(f" MCP 标记检测: {'存在' if has_marker else '不存在'}, stdout长度={len(stdout)}")

        # 查找所有 MCP 数据标记
        matches = self._MCP_DATA_PATTERN.findall(stdout)

        if not matches:
            logger.info(" 未找到 MCP 标记匹配，返回原始输出")
            return stdout, {}

        logger.info(f" 找到 {len(matches)} 个 MCP 标记匹配")

        # 按服务（技能）分组
        skill_calls = self._group_calls_by_skill(matches)

        if not skill_calls:
            # 没有有效的调用数据，只移除标记
            return self._MCP_DATA_PATTERN.sub("", stdout), {}

        #  构建元数据（不再注册引用）
        mcp_metadata = self._build_metadata(skill_calls)

        # 移除原始标记，得到纯净的用户 print 输出
        clean_stdout = self._MCP_DATA_PATTERN.sub("", stdout).strip()
        logger.info(f" clean_stdout 长度={len(clean_stdout)}, 是否为空={not clean_stdout}")

        # 如果用户没有显式 print 输出，使用 MCP result 数据
        if not clean_stdout:
            clean_stdout = self._extract_mcp_results(skill_calls)
            if not clean_stdout:
                clean_stdout = ""

        #  返回清洁输出和元数据
        return clean_stdout, mcp_metadata

    def _group_calls_by_skill(self, matches: list[str]) -> SkillCallsDict:
        """按技能分组 MCP 调用

        Args:
            matches: 正则匹配到的 JSON 字符串列表

        Returns:
            按技能名称分组的调用字典
        """
        skill_calls: SkillCallsDict = {}

        for match in matches:
            try:
                data = json.loads(match)
                skill = data.get("s", "")
                tool = data.get("t", "")
                result = data.get("r", "")

                if skill:
                    if skill not in skill_calls:
                        skill_calls[skill] = []
                    skill_calls[skill].append({"tool": tool, "result": result})
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f" 解析 MCP 数据标记失败: {e}")
                continue

        return skill_calls

    def _build_metadata(self, skill_calls: SkillCallsDict) -> dict[str, Any]:
        """构建 MCP 元数据（遵循 metadata.sources 标准约定）

        Args:
            skill_calls: 按技能分组的调用字典

        Returns:
            包含 sources 字段的元数据字典，供 SourceTracker 自动处理
        """
        sources: list[dict[str, object]] = []
        total_calls = 0

        for skill_name, calls in skill_calls.items():
            call_records = [{"tool_name": c.get("tool", ""), "result_preview": c.get("result", "")} for c in calls]
            sources.append(
                {
                    "type": "mcp",
                    "skill_name": skill_name,
                    "calls": call_records,
                }
            )
            total_calls += len(calls)
            logger.info(f" 提取 MCP 元数据: {skill_name} ({len(calls)} 次调用)")

        return {
            "sources": sources,
            "total_calls": total_calls,
        }

    def _extract_mcp_results(self, skill_calls: SkillCallsDict) -> str:
        """从 MCP 调用中提取 result 数据

        当用户没有显式 print 输出时，使用 MCP 返回的数据。

        Args:
            skill_calls: 按技能分组的调用字典

        Returns:
            拼接后的 result 内容
        """
        logger.info(" 用户无 print 输出，使用 MCP result 数据")

        mcp_results = []
        for _skill_name, calls in skill_calls.items():
            for call in calls:
                tool = call.get("tool", "unknown")
                result = call.get("result", "")
                if result:
                    mcp_results.append(f"[{tool}] {result}")

        return "\n\n".join(mcp_results) if mcp_results else ""
