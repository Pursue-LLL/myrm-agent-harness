"""Canonicalizer ensuring byte-level deterministic stability for tool prefixes.

[INPUT]
- agent.context_management.canonical_tool.canonical_tool_types::CanonicalToolDefinition,
  FrozenToolPrefixBundle, PrefixDriftDiagnosis, ToolDefinitionInput (POS: Types and models for canonical
  tool.)

[OUTPUT]
- rfc8785_canonicalize_json(): Canonicalize Python data structure strictly according to RFC 8785 (JCS).
- DeterministicToolSchemaCanonicalizer: Canonicalizer ensuring byte-level deterministic stability for tool
  prefixes.

[POS]
Canonicalizer ensuring byte-level deterministic stability for tool prefixes.
"""

# ============================================================================
# Deterministic Tool Schema Canonicalizer & Prefix Hasher Engine (Item 167)
# Strict RFC 8785 JSON canonicalization, deterministic alphabetical tool sorting,
# byte-level prefix freezing, and granular prefix drift diagnosis.
# ============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from .canonical_tool_types import (
    CanonicalToolDefinition,
    FrozenToolPrefixBundle,
    PrefixDriftDiagnosis,
    ToolDefinitionInput,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_sha256(data: bytes | str) -> str:
    """Compute deterministic SHA-256 hex digest for bytes or string."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def rfc8785_canonicalize_json(data: object) -> str:
    """Canonicalize Python data structure strictly according to RFC 8785 (JCS).

    Rules:
    - Object keys sorted lexicographically by Unicode code points.
    - No insignificant whitespace (no space after ':' or ',').
    - Numbers formatted without trailing decimals; NaN/Inf prohibited.
    - Strings escaped using standard minimal JSON escaping without ASCII forcing.
    """
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "true" if data else "false"
    if isinstance(data, int):
        return str(data)
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            raise ValueError(f"RFC 8785 disallows NaN and Infinity in JSON, got: {data}")
        # Normalize negative zero -0.0 to 0
        if data == 0.0:
            return "0"
        # Format integer-valued float as integer representation if exact
        if data.is_integer():
            return str(int(data))
        # Format standard float representation
        s = repr(data)
        return s
    if isinstance(data, str):
        # json.dumps handles valid JSON string escaping; ensure_ascii=False for UTF-8
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, (list, tuple)):
        items_str = ",".join(rfc8785_canonicalize_json(item) for item in data)
        return f"[{items_str}]"
    if isinstance(data, Mapping):
        # Sort keys lexicographically by string representation
        sorted_keys = sorted(str(k) for k in data.keys())
        entries: list[str] = []
        for k in sorted_keys:
            key_json = json.dumps(k, ensure_ascii=False)
            val_json = rfc8785_canonicalize_json(data[k])
            entries.append(f"{key_json}:{val_json}")
        return f"{{{','.join(entries)}}}"

    # Fallback for unrecognized types: coerce to string
    return json.dumps(str(data), ensure_ascii=False)


class DeterministicToolSchemaCanonicalizer:
    """Canonicalizer ensuring byte-level deterministic stability for tool prefixes."""

    def canonicalize_tool(self, tool: ToolDefinitionInput) -> CanonicalToolDefinition:
        """Canonicalize single tool specification into RFC 8785 canonical structure."""
        canonical_params_json = rfc8785_canonicalize_json(tool.parameters)
        parsed_params = json.loads(canonical_params_json)

        # Build normalized dictionary with sorted keys: description, name, parameters
        normalized_obj = {
            "description": tool.description.strip(),
            "name": tool.name.strip(),
            "parameters": parsed_params,
        }
        canonical_str = rfc8785_canonicalize_json(normalized_obj)
        canonical_bytes = canonical_str.encode("utf-8")
        tool_hash = _compute_sha256(canonical_bytes)

        return CanonicalToolDefinition(
            name=tool.name.strip(),
            description=tool.description.strip(),
            parameters_canonical_json=canonical_params_json,
            tool_sha256=tool_hash,
            byte_size=len(canonical_bytes),
        )

    def freeze_tool_prefix(
        self,
        tools: Sequence[ToolDefinitionInput],
    ) -> FrozenToolPrefixBundle:
        """Sort tools alphabetically by name, canonicalize schemas, and freeze byte payload."""
        # Enforce deterministic alphabetical tool ordering
        sorted_inputs = sorted(tools, key=lambda t: t.name.strip())
        canonical_tools = [self.canonicalize_tool(t) for t in sorted_inputs]

        # Assemble full canonical payload array strictly in sorted order
        tools_array_raw = [
            {
                "description": ct.description,
                "name": ct.name,
                "parameters": json.loads(ct.parameters_canonical_json),
            }
            for ct in canonical_tools
        ]

        full_payload_str = rfc8785_canonicalize_json(tools_array_raw)
        payload_bytes = full_payload_str.encode("utf-8")
        prefix_hash = _compute_sha256(payload_bytes)

        sorted_names = tuple(ct.name for ct in canonical_tools)

        logger.info(
            "Frozen tool prefix: %d tools, prefix_hash=%s, bytes=%d",
            len(canonical_tools),
            prefix_hash[:12],
            len(payload_bytes),
        )

        return FrozenToolPrefixBundle(
            prefix_hash=prefix_hash,
            canonical_payload_bytes=payload_bytes,
            tool_count=len(canonical_tools),
            sorted_tool_names=sorted_names,
            tools=tuple(canonical_tools),
            frozen_at_iso=_utc_now_iso(),
        )

    def diagnose_prefix_drift(
        self,
        prev_bundle: FrozenToolPrefixBundle,
        curr_bundle: FrozenToolPrefixBundle,
    ) -> PrefixDriftDiagnosis:
        """Diagnose byte-level differences and root-cause cache drift between tool bundles."""
        if prev_bundle.prefix_hash == curr_bundle.prefix_hash:
            return PrefixDriftDiagnosis(
                has_drift=False,
                previous_hash=prev_bundle.prefix_hash,
                current_hash=curr_bundle.prefix_hash,
                added_tools=(),
                removed_tools=(),
                modified_tools=(),
                detail_reason="Tool prefix is byte-for-byte identical. Prompt cache guaranteed stable.",
            )

        prev_map = {t.name: t.tool_sha256 for t in prev_bundle.tools}
        curr_map = {t.name: t.tool_sha256 for t in curr_bundle.tools}

        prev_names = set(prev_map)
        curr_names = set(curr_map)

        added = tuple(sorted(curr_names - prev_names))
        removed = tuple(sorted(prev_names - curr_names))
        modified: list[str] = []

        for name in sorted(prev_names & curr_names):
            if prev_map[name] != curr_map[name]:
                modified.append(name)

        reasons: list[str] = []
        if added:
            reasons.append(f"新增工具: {', '.join(added)}")
        if removed:
            reasons.append(f"移除工具: {', '.join(removed)}")
        if modified:
            reasons.append(f"参数/描述变更工具: {', '.join(modified)}")

        detail = "检测到工具前缀哈希漂移 (将导致前缀缓存失效): " + "; ".join(reasons)

        logger.warning(
            "Tool Prefix Drift detected: prev=%s, curr=%s, details=%s",
            prev_bundle.prefix_hash[:8],
            curr_bundle.prefix_hash[:8],
            detail,
        )

        return PrefixDriftDiagnosis(
            has_drift=True,
            previous_hash=prev_bundle.prefix_hash,
            current_hash=curr_bundle.prefix_hash,
            added_tools=added,
            removed_tools=removed,
            modified_tools=tuple(modified),
            detail_reason=detail,
        )
