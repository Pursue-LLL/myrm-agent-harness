from myrm_agent_harness.agent.security.ptc_verifier import extract_ptc_intent
from myrm_agent_harness.agent.security.tool_registry import (
    _PTC_SAFETY_METADATA,
    _PTC_TOOL_FLAT_INDEX,
    MCPAnnotations,
    SafetyMetadata,
    get_ptc_safety_metadata,
    register_ptc_safety_metadata,
    resolve_safety_metadata,
)


def test_extract_pure_ptc_success():
    """Test extracting intent from a valid, pure PTC command."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
_read_file(path='/workspace/repo', branch='main')
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    skill_name, tool_name, args = result
    assert skill_name == "mcp_github_skill"
    assert tool_name == "read_file"
    assert args == {"path": "/workspace/repo", "branch": "main"}

def test_extract_ptc_with_other_imports_rejected():
    """Test that importing anything other than skills.* is rejected for safety."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
import os
_read_file(path='/workspace')
"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_with_malicious_calls_rejected():
    """Test that calling anything other than allowed builtins and imported tools is rejected."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
_read_file(path='/workspace')
eval('os.system(\\"rm -rf /\\")')
"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_with_attribute_calls_rejected():
    """Test that methods on objects (Attribute calls) are rejected."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
res = _read_file(path='/workspace')
res.update({'malicious': True})
"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_with_safe_builtins_accepted():
    """Test that using safe builtins like print or dict is accepted."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
res = _read_file(path='/workspace')
print(dict(res))
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    skill_name, tool_name, _args = result
    assert skill_name == "mcp_github_skill"
    assert tool_name == "read_file"

def test_extract_ptc_with_loops_rejected():
    """Test that complex control flow like loops are rejected."""
    command = '''python -c "
from skills.mcp_github_skill import _read_file
for i in range(10):
    _read_file(path=f'/workspace/{i}')
"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_with_syntax_error():
    """Test that invalid python syntax returns None."""
    command = '''python -c "from skills import def"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_without_python_code():
    """Test that non-python commands return None."""
    command = '''echo "hello"'''
    result = extract_ptc_intent(command)
    assert result is None

def test_extract_ptc_without_underscore_func():
    """Test that a tool name without leading underscore is parsed correctly."""
    command = '''python -c "
from skills.mcp_github_skill import read_file
read_file(path='/workspace')
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    assert result[1] == "read_file"

def test_extract_ptc_with_complex_args():
    """Test that args failing literal_eval are ignored but script is still safe."""
    command = '''python -c "
from skills.mcp_github_skill import read_file
my_var = '/workspace'
read_file(path=my_var)
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    assert "path" not in result[2]

def test_extract_ptc_with_invalid_import():
    """Test import from without module name."""
    command = '''python -c "
from . import _read_file
"'''
    result = extract_ptc_intent(command)
    assert result is None


def test_extract_ptc_non_skill_from_import_rejected():
    """from import of non-skill module (not skills.*/tools.*/*_skill) is rejected."""
    command = '''python -c "
from utils.helper import do_something
do_something(arg='val')
"'''
    result = extract_ptc_intent(command)
    assert result is None


def test_extract_ptc_no_matching_import_returns_none():
    """Script with no from-import at all yields no skill_name → returns None."""
    command = '''python -c "
x = 1 + 2
print(x)
"'''
    result = extract_ptc_intent(command)
    assert result is None


def test_extract_ptc_with_list_arg():
    """ast.literal_eval for List argument in kwargs (line 149)."""
    command = '''python -c "
from skills.mcp_github_skill import _search
_search(paths=['/a', '/b', '/c'])
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    _, _, args = result
    assert args.get("paths") == ["/a", "/b", "/c"]


def test_extract_ptc_with_dict_arg():
    """ast.literal_eval for Dict argument in kwargs (line 149)."""
    command = '''python -c "
from skills.mcp_github_skill import _update
_update(config={'key': 'value', 'count': 3})
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    _, _, args = result
    assert args.get("config") == {"key": "value", "count": 3}


def test_extract_ptc_tools_module_without_skill_suffix():
    """from tools.* passes safety check but extract_ptc_intent requires *_skill suffix."""
    command = '''python -c "
from tools.my_tool import _run
_run(param='hello')
"'''
    result = extract_ptc_intent(command)
    assert result is None, "tools.my_tool not ending in _skill → no PTC intent extracted"


def test_extract_ptc_tools_skill_module():
    """from tools.my_tool_skill import _run → both safety check and intent extraction pass."""
    command = '''python -c "
from tools.my_tool_skill import _run
_run(param='hello')
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    skill_name, tool_name, args = result
    assert skill_name == "my_tool_skill"
    assert tool_name == "run"
    assert args == {"param": "hello"}


def test_extract_ptc_skill_suffix_module():
    """Import from module ending with _skill is accepted."""
    command = '''python -c "
from custom_skill import _process
_process(data='test')
"'''
    result = extract_ptc_intent(command)
    assert result is not None
    skill_name, _tool_name, _ = result
    assert skill_name == "custom_skill"


class TestPTCSafetyMetadataRegistry:
    """Tests for register_ptc_safety_metadata and get_ptc_safety_metadata."""

    def setup_method(self) -> None:
        self._backup = dict(_PTC_SAFETY_METADATA)
        self._flat_backup = dict(_PTC_TOOL_FLAT_INDEX)

    def teardown_method(self) -> None:
        _PTC_SAFETY_METADATA.clear()
        _PTC_SAFETY_METADATA.update(self._backup)
        _PTC_TOOL_FLAT_INDEX.clear()
        _PTC_TOOL_FLAT_INDEX.update(self._flat_backup)

    def test_register_and_get(self):
        meta = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
        annotations: MCPAnnotations = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
        register_ptc_safety_metadata("my_skill", "read_file", meta, annotations)

        result = get_ptc_safety_metadata("my_skill", "read_file")
        assert result is not None
        assert result[0] == meta
        assert result[1] == annotations

    def test_register_new_skill_creates_dict(self):
        register_ptc_safety_metadata(
            "brand_new_skill",
            "action",
            SafetyMetadata(),
            {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        )
        assert "brand_new_skill" in _PTC_SAFETY_METADATA
        assert "action" in _PTC_SAFETY_METADATA["brand_new_skill"]

    def test_get_nonexistent_returns_none(self):
        assert get_ptc_safety_metadata("nonexistent_skill", "no_tool") is None

    def test_register_populates_flat_index(self):
        meta = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
        register_ptc_safety_metadata("my_skill", "mcp_read_tool", meta, {"readOnlyHint": True})
        assert _PTC_TOOL_FLAT_INDEX["mcp_read_tool"] is meta

    def test_resolve_safety_metadata_falls_back_to_flat_index(self):
        meta = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
        register_ptc_safety_metadata("my_skill", "mcp_list_items", meta, {"readOnlyHint": True})
        resolved = resolve_safety_metadata("mcp_list_items")
        assert resolved.is_read_only is True
        assert resolved.is_concurrent_safe is True

    def test_resolve_safety_metadata_builtin_takes_priority(self):
        """Built-in TOOL_SAFETY_METADATA entries always override MCP dynamic entries."""
        register_ptc_safety_metadata(
            "my_skill", "file_read_tool",
            SafetyMetadata(is_destructive=True),
            {"destructiveHint": True},
        )
        resolved = resolve_safety_metadata("file_read_tool")
        assert resolved.is_read_only is True
        assert resolved.is_destructive is False

    def test_resolve_safety_metadata_unknown_tool_returns_defaults(self):
        resolved = resolve_safety_metadata("completely_unknown_tool_xyz")
        assert resolved.is_read_only is False
        assert resolved.is_concurrent_safe is False
        assert resolved.is_destructive is False
