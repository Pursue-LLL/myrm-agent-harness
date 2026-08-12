# schema/

## Overview
Outbound tool schema normalization for provider-compatible LLM dispatch: OpenAI-compatible normalizer plus Anthropic-specific keyword stripping and property-level branch merging.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-package exports. | — |
| normalizer.py | Core | `normalize_tool_schema` entry point: `$ref`/`$defs` inlining, top-level composite handling (single-branch extraction, `allOf` conjunctive merge / `anyOf`/`oneOf` alternative merge with exclusivity hint folding, outer metadata preserved onto merged branches), nested property-level union merging, orphan required pruning, missing-type inference, enum cleanup. | ✅ |
| property_merge.py | Core | Property-level branch merging: `merge_allof_branches` (conjunctive: required union, same-name `const`/`enum` intersection) vs `merge_union_object_branches` (alternative: required dropped except common discriminators, `const`/`enum` union, keyword-aware exclusivity hint), `apply_union_hint`, per-property `merge_union_property`/`intersect_property`. Metadata (`title`/`description`/`default`) is merged symmetrically across branches via `_merge_metadata`, mirroring inbound union/intersection semantics so LLM-facing guidance is never dropped. | ✅ |
| anthropic_strip.py | Core | Anthropic/Claude unsupported JSON Schema keyword stripping (minimum/maxItems/pattern/format/title/default) with constraint-to-description folding; `is_anthropic_model` gate. | ✅ |

## Key Dependencies

- `toolkits.llms.adapters.model_capability` (provider detection)
- `utils.json_parsing`
