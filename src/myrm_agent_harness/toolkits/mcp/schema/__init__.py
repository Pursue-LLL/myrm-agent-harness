"""MCP tool JSON Schema normalization sub-package.

Aggregates the MCP inbound schema pipeline: ``$ref``/``$defs`` inlining and
cache-stable canonicalization (``normalize``), composite-keyword flattening and
const-union collapsing (``composite``), and runtime argument coercion
(``coerce``).

[INPUT]
- raw MCP ``inputSchema`` dicts from third-party MCP servers

[OUTPUT]
- normalize: canonicalize_schema_for_cache, flatten_json_schema, flatten_deep_schema, nest_flat_arguments
- composite: collapse_const_unions, flatten_top_level_composite
- coerce: coerce_arguments_by_schema, prepare_mcp_call_arguments, get_schema_coercion_stats

[POS]
MCP inbound tool schema normalization — cache-stable canonicalization, $ref
inlining, composite flattening, and argument coercion for LLM compatibility.
"""

from .coerce import (
    coerce_arguments_by_schema,
    coerce_value,
    get_schema_coercion_stats,
    prepare_mcp_call_arguments,
    reset_schema_coercion_stats,
)
from .composite import (
    collapse_const_unions,
    flatten_top_level_composite,
)
from .normalize import (
    FlattenMeta,
    analyze_schema_complexity,
    canonicalize_schema_for_cache,
    flatten_deep_schema,
    flatten_json_schema,
    has_dot_keys,
    nest_flat_arguments,
)

__all__ = [
    "FlattenMeta",
    "analyze_schema_complexity",
    "canonicalize_schema_for_cache",
    "coerce_arguments_by_schema",
    "coerce_value",
    "collapse_const_unions",
    "flatten_deep_schema",
    "flatten_json_schema",
    "flatten_top_level_composite",
    "get_schema_coercion_stats",
    "has_dot_keys",
    "nest_flat_arguments",
    "prepare_mcp_call_arguments",
    "reset_schema_coercion_stats",
]
