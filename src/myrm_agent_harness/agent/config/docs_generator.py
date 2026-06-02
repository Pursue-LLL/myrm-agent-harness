"""配置文档自动生成器

从 Pydantic schema 自动生成配置文档，确保文档永不过时。

[INPUT]

[OUTPUT]
- generate_config_docs(): 生成 Markdown 格式的配置文档

[POS]
Configuration documentation generator. Auto-generates config reference docs by reflecting Pydantic schemas.

"""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .llm import AgentConfig, LLMConfig


def _get_type_name(field_type: type) -> str:
    """获取类型的可读名称"""
    origin = get_origin(field_type)
    if origin is None:
        if hasattr(field_type, "__name__"):
            return field_type.__name__
        return str(field_type)

    args = get_args(field_type)
    if origin is list:
        inner = _get_type_name(args[0]) if args else "Any"
        return f"list[{inner}]"
    elif origin is dict:
        key_type = _get_type_name(args[0]) if args else "Any"
        val_type = _get_type_name(args[1]) if len(args) > 1 else "Any"
        return f"dict[{key_type}, {val_type}]"
    elif origin is type(None) or (hasattr(origin, "__name__") and origin.__name__ == "UnionType"):
        non_none_types = [arg for arg in args if arg is not type(None)]
        if len(non_none_types) == 1:
            return f"{_get_type_name(non_none_types[0])} | None"
        return " | ".join(_get_type_name(arg) for arg in args)
    else:
        return str(field_type)


def _generate_field_doc(field_name: str, field_info: FieldInfo, field_type: type) -> str:
    """生成单个字段的文档"""
    lines = [f"### `{field_name}`"]

    type_name = _get_type_name(field_type)
    lines.append(f"- **Type**: `{type_name}`")

    if field_info.is_required():
        lines.append("- **Required**: Yes")
    else:
        default_val = field_info.default
        if default_val is not None:
            lines.append(f"- **Default**: `{default_val}`")
        else:
            lines.append("- **Default**: `None`")

    if field_info.description:
        lines.append(f"- **Description**: {field_info.description}")

    if hasattr(field_info, "ge") and field_info.ge is not None:
        lines.append(f"- **Min value**: {field_info.ge}")
    if hasattr(field_info, "le") and field_info.le is not None:
        lines.append(f"- **Max value**: {field_info.le}")
    if hasattr(field_info, "gt") and field_info.gt is not None:
        lines.append(f"- **Must be greater than**: {field_info.gt}")

    return "\n".join(lines)


def _generate_model_doc(model_cls: type[BaseModel], title: str) -> str:
    """生成 Pydantic Model 的完整文档"""
    lines = [f"## {title}", ""]

    if model_cls.__doc__:
        lines.append(model_cls.__doc__.strip())
        lines.append("")

    lines.append("### Fields")
    lines.append("")

    for field_name, field_info in model_cls.model_fields.items():
        field_type = model_cls.model_fields[field_name].annotation
        lines.append(_generate_field_doc(field_name, field_info, field_type))
        lines.append("")

    return "\n".join(lines)


def generate_config_docs() -> str:
    """生成配置文档

    从 Pydantic schema 自动生成 Markdown 格式的配置文档。

    Returns:
        Markdown 格式的完整配置文档
    """
    sections = [
        "# Myrm Agent Configuration Guide",
        "",
        "This document is auto-generated from Pydantic schemas. Do not edit manually.",
        "",
        "---",
        "",
    ]

    sections.append(_generate_model_doc(LLMConfig, "LLMConfig"))
    sections.append("---\n")

    sections.append(_generate_model_doc(AgentConfig, "AgentConfig"))
    sections.append("---\n")

    sections.append("## StorageConfig")
    sections.append("")
    sections.append("Storage configuration (dataclass, not validated by Pydantic).")
    sections.append("")
    sections.append("### Fields")
    sections.append("")
    sections.append("- `backend_type`: Storage backend type (default: `local`)")
    sections.append("- `root_dir`: Local storage root directory (default: `./workspace`)")
    sections.append("- `virtual_mode`: Enable sandbox virtualization (default: `True`)")
    sections.append("- `custom_params`: Custom parameters for backend (optional)")
    sections.append("")

    sections.append("---\n")
    sections.append("## Configuration Examples")
    sections.append("")
    sections.append("### Minimal Configuration")
    sections.append("")
    sections.append("```python")
    sections.append("from myrm_agent_harness.agent.config import AgentConfig, LLMConfig")
    sections.append("")
    sections.append('config = AgentConfig(llm=LLMConfig(model="gpt-4", api_key="sk-..."))')
    sections.append("```")
    sections.append("")

    sections.append("### From Environment Variables")
    sections.append("")
    sections.append("```python")
    sections.append("from myrm_agent_harness.agent.config import AgentConfig")
    sections.append("")
    sections.append("config = AgentConfig.from_env()  # Loads from MYRM_* env vars")
    sections.append("```")
    sections.append("")

    return "\n".join(sections)


__all__ = ["generate_config_docs"]
