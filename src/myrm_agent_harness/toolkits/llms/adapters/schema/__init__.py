"""Tool schema normalization for OpenAI-compatible providers.

Aggregates outbound tool schema normalization: entry-point ``normalize_tool_schema``
(``normalizer``), property-level composite-keyword merging (``property_merge``),
and Anthropic-specific keyword stripping (``anthropic_strip``).

[INPUT]
- OpenAI-format tool dicts ``{type: "function", function: {...}}``
- model_name for provider-specific sanitization

[OUTPUT]
- normalizer::normalize_tool_schema: Normalize an OpenAI-format tool schema for provider compatibility.
- property_merge: merge_allof_branches, merge_union_object_branches, apply_union_hint, merge_union_property, intersect_property
- anthropic_strip: is_anthropic_model, strip_anthropic_unsupported

[POS]
Outbound tool schema normalization for OpenAI-compatible LLM providers.
"""

from .anthropic_strip import is_anthropic_model, strip_anthropic_unsupported
from .normalizer import normalize_tool_schema
from .property_merge import (
    apply_union_hint,
    intersect_property,
    merge_allof_branches,
    merge_union_object_branches,
    merge_union_property,
    preserve_metadata,
)

__all__ = [
    "apply_union_hint",
    "intersect_property",
    "is_anthropic_model",
    "merge_allof_branches",
    "merge_union_object_branches",
    "merge_union_property",
    "normalize_tool_schema",
    "preserve_metadata",
    "strip_anthropic_unsupported",
]
