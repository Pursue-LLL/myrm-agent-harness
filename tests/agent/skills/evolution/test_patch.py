
from myrm_agent_harness.agent.skills.evolution.pipeline.patch import (
    PatchType,
    apply_skill_patch,
    detect_patch_type,
    parse_multi_file_full,
)


def test_detect_patch_type_multi_file():
    content = "*** Begin Files\n*** File: SKILL.md\ncontent"
    assert detect_patch_type(content) == PatchType.MULTI_FILE_FULL

def test_detect_patch_type_diff():
    content = "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"
    assert detect_patch_type(content) == PatchType.DIFF

def test_detect_patch_type_full():
    content = "just some new skill content"
    assert detect_patch_type(content) == PatchType.FULL

def test_parse_multi_file_full():
    content = "*** File: SKILL.md\nhello\n*** File: test.py\nworld\n"
    files = parse_multi_file_full(content)
    assert files == {"SKILL.md": "hello", "test.py": "world"}

def test_parse_multi_file_full_empty():
    assert parse_multi_file_full("no headers") == {}

def test_apply_skill_patch_full():
    result = apply_skill_patch("old", "new full")
    assert result.success is True
    assert result.content == "new full"
    assert result.num_changes_applied == 1

def test_apply_skill_patch_multi_file():
    llm_output = "*** File: SKILL.md\nhello\n*** File: scripts/test.py\nworld"
    result = apply_skill_patch("old", llm_output, patch_type=PatchType.MULTI_FILE_FULL)
    assert result.success is True
    assert result.content == "hello"
    assert result.auxiliary_files == {"scripts/test.py": "world"}
    assert result.num_changes_applied == 2

def test_apply_skill_patch_multi_file_missing_skill():
    llm_output = "*** File: scripts/test.py\nworld"
    result = apply_skill_patch("old", llm_output, patch_type=PatchType.MULTI_FILE_FULL)
    assert result.success is False
    assert "missing SKILL.md" in result.error_message

def test_apply_skill_patch_multi_file_no_blocks():
    result = apply_skill_patch("old", "no blocks", patch_type=PatchType.MULTI_FILE_FULL)
    assert result.success is False
    assert "No *** File:" in result.error_message

def test_apply_skill_patch_diff():
    original = "def foo():\n    return 1"
    llm_output = "<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE"
    result = apply_skill_patch(original, llm_output, patch_type=PatchType.DIFF)
    assert result.success is True
    assert result.content == "def foo():\n    return 2"
    assert result.num_changes_applied == 1

def test_apply_skill_patch_diff_no_blocks():
    original = "def foo():\n    return 1"
    llm_output = "no diff blocks"
    result = apply_skill_patch(original, llm_output, patch_type=PatchType.DIFF)
    assert result.success is False
    assert "No SEARCH/REPLACE blocks found" in result.error_message

def test_apply_skill_patch_diff_failing_patch():
    original = "def foo():\n    return 1"
    llm_output = "<<<<<<< SEARCH\nreturn 5\n=======\nreturn 6\n>>>>>>> REPLACE"
    result = apply_skill_patch(original, llm_output, patch_type=PatchType.DIFF)
    assert result.success is False
    assert "SEARCH text not found in block" in result.error_message
