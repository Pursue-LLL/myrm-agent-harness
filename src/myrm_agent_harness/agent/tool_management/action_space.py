"""
[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain 工具基类)

[OUTPUT]
- ActionSpaceProfiler: 提供工具集认知负载与动作空间复杂度计算能力

[POS]
动作空间量化引擎。通过深层解析工具的 Schema，量化计算大模型的动作空间复杂度（ASCS），用于前端展示和风控。

 更新规则：修改此文件后，请更新头注释 + 所属文件夹 _ARCH.md
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool


class ActionSpaceProfiler:
    """大模型动作空间复杂度计算引擎 (Action Space Complexity Score - ASCS)"""

    BASE_TOOL_COST = 10
    PARAM_COST = 5
    NESTING_COST = 10

    # 外部未解析工具的默认惩罚值（当无法获取真实 schema 时）
    ESTIMATED_MCP_TOOL_COST = 400
    ESTIMATED_BUILTIN_TOOL_COST = 100

    @classmethod
    def calculate_score(cls, tools: Sequence[BaseTool | dict[str, Any]]) -> int:
        """
        计算给定工具集的动作空间复杂度分数 (ASCS)。
        支持传入 LangChain BaseTool 实例，或原生的 OpenAPI Schema 字典（方便业务层直接查库调用）。

        Args:
            tools: 工具对象列表 (BaseTool 实例或 Schema 字典)

        Returns:
            int: 动作空间复杂度分数 (分数越高，大模型幻觉率越大)
        """
        total_score = 0

        for tool in tools:
            # 基础成本：每一个工具的存在都会分散 LLM 的注意力
            total_score += cls.BASE_TOOL_COST

            schema = {}
            desc_len = 0

            if isinstance(tool, dict):
                # 直接传入了 Schema 字典
                schema = tool
                desc_len = len(schema.get("description", ""))
            else:
                # 解析 BaseTool 实例
                schema = cls._get_tool_schema(tool) or {}
                desc_len = len(tool.description or "")

            # 解析参数复杂度
            if "properties" in schema:
                total_score += cls._calculate_schema_complexity(schema["properties"])

            # 简易 Token 成本估算 (描述长度 / 50)
            total_score += desc_len // 50

        return total_score

    @classmethod
    def estimate_external_load(cls, mcp_count: int, builtin_count: int) -> int:
        """
        在无法实时获取外部 MCP 服务完整 Schema 的情况下，提供科学的保守估算值。
        因为外部服务往往包含多个具备极深嵌套对象的工具。
        """
        return (mcp_count * cls.ESTIMATED_MCP_TOOL_COST) + (builtin_count * cls.ESTIMATED_BUILTIN_TOOL_COST)

    @classmethod
    def _calculate_schema_complexity(cls, properties: dict[str, Any], depth: int = 1) -> int:
        """递归计算 Schema 复杂度"""
        score = 0
        for prop_info in properties.values():
            score += cls.PARAM_COST

            # 如果是嵌套对象，增加嵌套惩罚
            if prop_info.get("type") == "object" and "properties" in prop_info:
                score += cls.NESTING_COST * depth
                score += cls._calculate_schema_complexity(prop_info["properties"], depth + 1)

            # 枚举值也会增加选择负担
            if "enum" in prop_info:
                score += len(prop_info["enum"])

        return score

    @classmethod
    def _get_tool_schema(cls, tool: BaseTool) -> dict[str, Any] | None:
        """获取工具的 JSON Schema"""
        # BaseTool 的 args_schema 或直接转 dict
        if hasattr(tool, "args_schema") and tool.args_schema:
            if hasattr(tool.args_schema, "model_json_schema"):
                return tool.args_schema.model_json_schema()
            return tool.args_schema.schema() # type: ignore
        # 兼容 StructuredTool
        if hasattr(tool, "get_input_schema"):
            schema_model = tool.get_input_schema()
            if hasattr(schema_model, "model_json_schema"):
                return schema_model.model_json_schema()
            return schema_model.schema() # type: ignore
        return None
