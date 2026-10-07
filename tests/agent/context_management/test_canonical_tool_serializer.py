# ============================================================================
# Unit Tests: Deterministic Tool Schema Canonicalizer & Prefix Hasher (Item 167)
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.canonical_tool import (
    DeterministicToolSchemaCanonicalizer,
    ToolDefinitionInput,
    rfc8785_canonicalize_json,
)


def test_rfc8785_canonicalize_json_primitives_and_key_sorting() -> None:
    """Test RFC 8785 JSON canonicalization rules on primitives, keys and whitespaces."""
    # Key sorting: regardless of insertion order, keys must sort lexicographically
    dict_a = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    dict_b = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}

    canon_a = rfc8785_canonicalize_json(dict_a)
    canon_b = rfc8785_canonicalize_json(dict_b)

    assert canon_a == canon_b
    assert canon_a == '{"a":2,"m":{"a":4,"b":3},"z":1}'

    # No unnecessary whitespaces
    assert " " not in canon_a

    # Numbers and booleans
    assert rfc8785_canonicalize_json(True) == "true"
    assert rfc8785_canonicalize_json(False) == "false"
    assert rfc8785_canonicalize_json(None) == "null"
    assert rfc8785_canonicalize_json(-0.0) == "0"
    assert rfc8785_canonicalize_json(100.0) == "100"

    # NaN / Inf should raise ValueError per RFC 8785
    with pytest.raises(ValueError):
        rfc8785_canonicalize_json(float("nan"))
    with pytest.raises(ValueError):
        rfc8785_canonicalize_json(float("inf"))


def test_deterministic_tool_schema_canonicalization() -> None:
    """Test canonicalizing individual tool with nested reversed schemas produces identical hash."""
    canonicalizer = DeterministicToolSchemaCanonicalizer()

    schema_1 = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }

    # Same semantic schema with completely scrambled key insertion order
    schema_2 = {
        "required": ["query"],
        "properties": {
            "limit": {"default": 10, "type": "integer"},
            "query": {"description": "Search query", "type": "string"},
        },
        "type": "object",
    }

    t1 = ToolDefinitionInput(
        name="search_web",
        description="Search Google / Bing for facts",
        parameters=schema_1,
    )
    t2 = ToolDefinitionInput(
        name="search_web",
        description="Search Google / Bing for facts",
        parameters=schema_2,
    )

    c1 = canonicalizer.canonicalize_tool(t1)
    c2 = canonicalizer.canonicalize_tool(t2)

    assert c1.parameters_canonical_json == c2.parameters_canonical_json
    assert c1.tool_sha256 == c2.tool_sha256
    assert c1.byte_size == c2.byte_size
    assert len(c1.tool_sha256) == 64


def test_freeze_tool_prefix_alphabetical_sorting_and_byte_invariance() -> None:
    """Test tools provided in arbitrary orders yield 100% byte-for-byte identical prefix bundle."""
    canonicalizer = DeterministicToolSchemaCanonicalizer()

    tool_bash = ToolDefinitionInput(
        name="bash_exec",
        description="Run safe bash commands",
        parameters={"properties": {"cmd": {"type": "string"}}, "type": "object"},
    )
    tool_search = ToolDefinitionInput(
        name="web_search",
        description="Search the web",
        parameters={"properties": {"q": {"type": "string"}}, "type": "object"},
    )
    tool_file = ToolDefinitionInput(
        name="read_file",
        description="Read file contents",
        parameters={"properties": {"path": {"type": "string"}}, "type": "object"},
    )

    # Order 1: bash, search, file
    bundle_1 = canonicalizer.freeze_tool_prefix([tool_bash, tool_search, tool_file])
    # Order 2: search, file, bash
    bundle_2 = canonicalizer.freeze_tool_prefix([tool_search, tool_file, tool_bash])
    # Order 3: file, bash, search
    bundle_3 = canonicalizer.freeze_tool_prefix([tool_file, tool_bash, tool_search])

    # Alphabetical sorting must enforce: bash_exec, read_file, web_search
    expected_order = ("bash_exec", "read_file", "web_search")
    assert bundle_1.sorted_tool_names == expected_order
    assert bundle_2.sorted_tool_names == expected_order
    assert bundle_3.sorted_tool_names == expected_order

    # Byte-level and hash-level invariance
    assert bundle_1.prefix_hash == bundle_2.prefix_hash == bundle_3.prefix_hash
    assert bundle_1.canonical_payload_bytes == bundle_2.canonical_payload_bytes == bundle_3.canonical_payload_bytes
    assert bundle_1.tool_count == 3


def test_diagnose_prefix_drift_detection() -> None:
    """Test prefix drift diagnosis accurately pinpoints added, removed and modified tools."""
    canonicalizer = DeterministicToolSchemaCanonicalizer()

    tool_a = ToolDefinitionInput(
        name="tool_a",
        description="Alpha tool",
        parameters={"type": "object"},
    )
    tool_b = ToolDefinitionInput(
        name="tool_b",
        description="Beta tool",
        parameters={"type": "object"},
    )
    bundle_base = canonicalizer.freeze_tool_prefix([tool_a, tool_b])

    # 1. No drift
    diag_clean = canonicalizer.diagnose_prefix_drift(bundle_base, bundle_base)
    assert diag_clean.has_drift is False
    assert len(diag_clean.added_tools) == 0

    # 2. Add tool_c
    tool_c = ToolDefinitionInput(
        name="tool_c",
        description="Gamma tool",
        parameters={"type": "object"},
    )
    bundle_added = canonicalizer.freeze_tool_prefix([tool_a, tool_b, tool_c])
    diag_add = canonicalizer.diagnose_prefix_drift(bundle_base, bundle_added)
    assert diag_add.has_drift is True
    assert diag_add.added_tools == ("tool_c",)
    assert "新增工具: tool_c" in diag_add.detail_reason

    # 3. Remove tool_a
    bundle_removed = canonicalizer.freeze_tool_prefix([tool_b])
    diag_rem = canonicalizer.diagnose_prefix_drift(bundle_base, bundle_removed)
    assert diag_rem.has_drift is True
    assert diag_rem.removed_tools == ("tool_a",)
    assert "移除工具: tool_a" in diag_rem.detail_reason

    # 4. Modify tool_b description
    tool_b_mod = ToolDefinitionInput(
        name="tool_b",
        description="Beta tool updated doc",
        parameters={"type": "object"},
    )
    bundle_mod = canonicalizer.freeze_tool_prefix([tool_a, tool_b_mod])
    diag_mod = canonicalizer.diagnose_prefix_drift(bundle_base, bundle_mod)
    assert diag_mod.has_drift is True
    assert diag_mod.modified_tools == ("tool_b",)
    assert "参数/描述变更工具: tool_b" in diag_mod.detail_reason
