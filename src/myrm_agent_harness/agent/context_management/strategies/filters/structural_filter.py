"""结构化数据过滤器

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- base::BaseFilter, FilterContext, FilterResult (POS: 过滤器基类和数据结构)
- utils.text_utils::get_token_count (POS: Token 计数工具)
- typing::Callable (POS: Python 类型提示)

[OUTPUT]
- StructuralFilter: 结构化数据过滤器类（纯代码提取，不依赖 LLM）

[POS]
Structural data filter. Extracts structure from JSON/XML/code/CSV/YAML/log files using pure code with zero LLM cost and fast response.

"""

import json
import re
from collections.abc import Callable

from myrm_agent_harness.utils.text_utils import get_token_count

from .base import BaseFilter, ContentType, FilterContext, FilterResult, generate_smart_read_suggestions


class StructuralFilter(BaseFilter):
    """结构化数据过滤器

    使用代码提取结构信息，适用于 JSON/XML/代码/CSV/YAML/LOG 等结构化数据。
    """

    def __init__(self) -> None:
        # 内容类型到处理函数的映射
        self._handlers: dict[ContentType, Callable[[FilterContext], tuple[str, str]]] = {
            "json": self._extract_json_structure,
            "xml": self._extract_xml_structure,
            "code": self._extract_code_structure,
            "csv": self._extract_csv_structure,
            "yaml": self._extract_yaml_structure,
            "log": self._extract_log_structure,
        }

    async def filter(self, context: FilterContext) -> FilterResult:
        """执行结构化过滤

        Args:
            context: 过滤上下文

        Returns:
            FilterResult 过滤结果
        """
        handler = self._handlers.get(context.content_type)
        if handler:
            summary, structure_overview = handler(context)
        else:
            # 回退到通用处理
            summary, structure_overview = self._extract_generic_structure(context)

        total_lines = len(context.content.splitlines())

        # 使用智能读取建议
        read_suggestions = generate_smart_read_suggestions(
            file_path=context.file_path, total_lines=total_lines, content_type=context.content_type
        )

        return FilterResult(
            file_path=context.file_path,
            content_type=context.content_type,
            total_lines=total_lines,
            total_chars=len(context.content),
            estimated_tokens=get_token_count(context.content),
            summary=summary,
            structure_overview=structure_overview,
            read_suggestions=read_suggestions,
            llm_generated=False,  # 结构化过滤不使用 LLM
        )

    def _extract_json_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取 JSON 结构信息

        Returns:
            (summary, structure_overview)
        """
        try:
            data = json.loads(context.content)
        except json.JSONDecodeError:
            return "JSON 解析失败", "无法解析 JSON 结构"

        if isinstance(data, list):
            return self._extract_json_array_structure(data, context.user_query)
        elif isinstance(data, dict):
            return self._extract_json_object_structure(data, context.user_query)
        else:
            return f"JSON 原始值: {type(data).__name__}", str(data)[:200]

    def _extract_json_array_structure(self, data: list[object], user_query: str) -> tuple[str, str]:
        """提取 JSON 数组结构"""
        total = len(data)
        summary_parts = [f"JSON 数组，共 {total} 个元素"]

        if not data:
            return "空 JSON 数组", "[]"

        # 分析第一个元素的结构
        first = data[0]
        if isinstance(first, dict):
            keys = list(first.keys())
            summary_parts.append(f"每个元素包含 {len(keys)} 个字段")

            # 构建结构概览
            structure_lines = [f"数组元素结构 (共 {total} 个):"]
            for key in keys[:15]:
                value = first.get(key)
                value_type = self._get_value_type_desc(value)
                # 如果是简单值，显示示例
                if isinstance(value, (str, int, float, bool)) and value is not None:
                    sample = str(value)[:50]
                    structure_lines.append(f" - {key}: {value_type} (示例: {sample})")
                else:
                    structure_lines.append(f" - {key}: {value_type}")

            if len(keys) > 15:
                structure_lines.append(f" ... 还有 {len(keys) - 15} 个字段")

            structure_overview = "\n".join(structure_lines)

            # 如果有用户查询，尝试找到相关字段
            if user_query:
                relevant = self._find_relevant_keys(keys, user_query)
                if relevant:
                    summary_parts.append(f"可能相关的字段: {', '.join(relevant)}")

        else:
            structure_overview = f"数组元素类型: {type(first).__name__}\n示例: {str(first)[:200]}"

        return " | ".join(summary_parts), structure_overview

    def _extract_json_object_structure(self, data: dict[str, object], user_query: str) -> tuple[str, str]:
        """提取 JSON 对象结构"""
        keys = list(data.keys())
        summary_parts = [f"JSON 对象，共 {len(keys)} 个键"]

        # 构建结构概览
        structure_lines = ["对象结构:"]
        for key in keys[:20]:
            value = data.get(key)
            value_type = self._get_value_type_desc(value)

            # 如果是简单值，显示示例
            if isinstance(value, (str, int, float, bool)) and value is not None:
                sample = str(value)[:50]
                structure_lines.append(f" - {key}: {value_type} (值: {sample})")
            else:
                structure_lines.append(f" - {key}: {value_type}")

        if len(keys) > 20:
            structure_lines.append(f" ... 还有 {len(keys) - 20} 个键")

        structure_overview = "\n".join(structure_lines)

        # 如果有用户查询，尝试找到相关字段
        if user_query:
            relevant = self._find_relevant_keys(keys, user_query)
            if relevant:
                summary_parts.append(f"可能相关的键: {', '.join(relevant)}")

        return " | ".join(summary_parts), structure_overview

    def _get_value_type_desc(self, value: object) -> str:
        """获取值的类型描述"""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "bool"
        elif isinstance(value, int):
            return "int"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, str):
            return f"str[{len(value)}]"
        elif isinstance(value, list):
            return f"list[{len(value)}]"
        elif isinstance(value, dict):
            return f"dict[{len(value)}]"
        else:
            return type(value).__name__

    def _find_relevant_keys(self, keys: list[str], query: str) -> list[str]:
        """根据查询找到可能相关的键"""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        relevant = []
        for key in keys:
            key_lower = key.lower()
            # 完全匹配
            if key_lower in query_lower or any(word in key_lower for word in query_words if len(word) > 2):
                relevant.append(key)

        return relevant[:5]  # 最多返回 5 个

    def _extract_xml_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取 XML 结构信息"""
        content = context.content

        # 提取根元素
        root_match = re.search(r"<(\w+)[^>]*>", content)
        root_tag = root_match.group(1) if root_match else "unknown"

        # 统计标签
        tags = re.findall(r"<(\w+)[^>]*>", content)
        tag_counts: dict[str, int] = {}
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # 构建摘要
        summary = f"XML 文档，根元素: <{root_tag}>，共 {len(tags)} 个标签"

        # 构建结构概览
        structure_lines = [f"根元素: <{root_tag}>", "标签统计:"]
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        for tag, count in sorted_tags[:15]:
            structure_lines.append(f" - <{tag}>: {count} 次")

        if len(sorted_tags) > 15:
            structure_lines.append(f" ... 还有 {len(sorted_tags) - 15} 种标签")

        return summary, "\n".join(structure_lines)

    def _extract_code_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取代码结构信息"""
        content = context.content
        lines = content.splitlines()

        # Python 定义
        py_classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)
        py_funcs = re.findall(r"^def\s+(\w+)", content, re.MULTILINE)
        py_async_funcs = re.findall(r"^async\s+def\s+(\w+)", content, re.MULTILINE)

        # JavaScript/TypeScript 定义
        js_funcs = re.findall(r"(?:function|const|let|var)\s+(\w+)\s*[=(]", content)
        js_classes = re.findall(r"class\s+(\w+)", content)

        # 构建摘要
        summary_parts = [f"代码文件，{len(lines)} 行"]

        if py_classes or py_funcs or py_async_funcs:
            summary_parts.append(f"Python: {len(py_classes)} 类, {len(py_funcs) + len(py_async_funcs)} 函数")
        if js_funcs or js_classes:
            summary_parts.append(f"JS/TS: {len(js_classes)} 类, {len(js_funcs)} 函数")

        # 构建结构概览
        structure_lines = ["代码结构:"]

        if py_classes:
            structure_lines.append("Python 类:")
            for cls in py_classes[:10]:
                structure_lines.append(f" - class {cls}")

        if py_funcs or py_async_funcs:
            structure_lines.append("Python 函数:")
            for func in (py_funcs + py_async_funcs)[:15]:
                structure_lines.append(f" - def {func}")

        if js_classes:
            structure_lines.append("JavaScript 类:")
            for cls in js_classes[:10]:
                structure_lines.append(f" - class {cls}")

        if js_funcs:
            structure_lines.append("JavaScript 函数:")
            unique_funcs = list(dict.fromkeys(js_funcs))[:15]
            for func in unique_funcs:
                structure_lines.append(f" - {func}")

        return " | ".join(summary_parts), "\n".join(structure_lines)

    def _extract_csv_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取 CSV 结构信息"""
        lines = context.content.splitlines()
        total_lines = len(lines)

        if not lines:
            return "空 CSV 文件", "无数据"

        # 检测分隔符
        first_line = lines[0]
        delimiter = ","
        for d in [",", "\t", ";"]:
            if d in first_line:
                delimiter = d
                break

        # 提取表头
        headers = first_line.split(delimiter)
        headers = [h.strip().strip('"').strip("'") for h in headers]

        # 分析数据行
        data_lines = lines[1:6]  # 取前 5 行数据
        summary_parts = [f"CSV 文件，共 {total_lines} 行，{len(headers)} 列"]

        # 构建结构概览
        structure_lines = ["列信息:"]
        for i, header in enumerate(headers[:15]):
            # 尝试获取示例值
            sample_values = []
            for data_line in data_lines:
                cols = data_line.split(delimiter)
                if i < len(cols):
                    sample_values.append(cols[i].strip().strip('"').strip("'")[:30])
            sample = sample_values[0] if sample_values else ""
            structure_lines.append(f" - {header}: {sample}")

        if len(headers) > 15:
            structure_lines.append(f" ... 还有 {len(headers) - 15} 列")

        return " | ".join(summary_parts), "\n".join(structure_lines)

    def _extract_yaml_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取 YAML 结构信息"""
        lines = context.content.splitlines()
        total_lines = len(lines)

        # 提取顶级键
        top_keys: list[str] = []
        for line in lines:
            # 匹配顶级键（没有缩进的 key:）
            match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*", line)
            if match:
                top_keys.append(match.group(1))

        summary = f"YAML 配置，共 {total_lines} 行，{len(top_keys)} 个顶级键"

        # 构建结构概览
        structure_lines = ["顶级键:"]
        for key in top_keys[:20]:
            structure_lines.append(f" - {key}")

        if len(top_keys) > 20:
            structure_lines.append(f" ... 还有 {len(top_keys) - 20} 个键")

        return summary, "\n".join(structure_lines)

    def _extract_log_structure(self, context: FilterContext) -> tuple[str, str]:
        """提取日志结构信息"""
        lines = context.content.splitlines()
        total_lines = len(lines)

        # 统计日志级别
        level_counts: dict[str, int] = {"ERROR": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
        for line in lines:
            line_upper = line.upper()
            for level in level_counts:
                if level in line_upper:
                    level_counts[level] += 1
                    break

        # 构建摘要
        summary_parts = [f"日志文件，共 {total_lines} 行"]
        non_zero_levels = [(k, v) for k, v in level_counts.items() if v > 0]
        if non_zero_levels:
            level_str = ", ".join(f"{k}: {v}" for k, v in non_zero_levels)
            summary_parts.append(level_str)

        # 构建结构概览
        structure_lines = ["日志统计:"]
        for level, count in level_counts.items():
            if count > 0:
                structure_lines.append(f" - {level}: {count} 条")

        # 显示最后几条错误或警告
        error_lines = [line for line in lines[-50:] if "ERROR" in line.upper() or "WARNING" in line.upper()]
        if error_lines:
            structure_lines.append("\n最近的错误/警告:")
            for line in error_lines[-5:]:
                structure_lines.append(f" {line[:100]}")

        return " | ".join(summary_parts), "\n".join(structure_lines)

    def _extract_generic_structure(self, context: FilterContext) -> tuple[str, str]:
        """通用结构提取（回退方案）"""
        lines = context.content.splitlines()
        total_lines = len(lines)

        summary = f"{context.content_type} 内容，共 {total_lines} 行"

        # 显示前几行作为预览
        preview_lines = lines[:10]
        structure_overview = "内容预览:\n" + "\n".join(f" {i + 1}: {line[:80]}" for i, line in enumerate(preview_lines))
        if total_lines > 10:
            structure_overview += f"\n  ... 还有 {total_lines - 10} 行"

        return summary, structure_overview
