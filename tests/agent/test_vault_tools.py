import shutil
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.vault_tools import vault_extract_tool, vault_get_tool, vault_put_tool


@pytest.fixture
def temp_workspace(tmp_path):
    # Setup temporary workspace for vault
    vault_dir = tmp_path / ".agent" / "vault"
    vault_dir.mkdir(parents=True)
    yield str(tmp_path)
    shutil.rmtree(tmp_path)

@pytest.fixture
def mock_context(temp_workspace):
    with patch("myrm_agent_harness.agent.meta_tools.file_ops.vault_tools._get_workspace_root", return_value=temp_workspace):
        yield temp_workspace

@pytest.mark.asyncio
async def test_vault_put_and_get(mock_context):
    # Test Put
    content = "Hello, massive world!" * 100
    res_put = await vault_put_tool.coroutine(content=content, filename="test.txt")
    assert res_put["success"] is True
    assert "vault://" in res_put["vault_pointer"]
    pointer = res_put["vault_pointer"]

    # Test Get
    res_get = await vault_get_tool.coroutine(vault_pointer=pointer, preview_only=False)
    assert res_get["success"] is True
    assert res_get["content"] == content
    assert res_get["is_truncated"] is False
    assert res_get["metadata"]["filename"] == "test.txt"

@pytest.mark.asyncio
async def test_vault_get_preview_truncation(mock_context):
    # Test Put > 2000 chars
    content = "A" * 3000
    res_put = await vault_put_tool.coroutine(content=content, filename="large.txt")
    pointer = res_put["vault_pointer"]

    # Test Get preview_only=True
    res_get = await vault_get_tool.coroutine(vault_pointer=pointer, preview_only=True)
    assert res_get["success"] is True
    assert len(res_get["content"]) < 3000
    assert "TRUNCATED" in res_get["content"]
    assert res_get["is_truncated"] is True

@pytest.mark.asyncio
async def test_vault_extract_tool_keyword(mock_context):
    # Setup massive file with keyword
    lines = [f"Line {i}\n" for i in range(100)]
    lines[50] = "This is a SECRET_KEY line.\n"
    content = "".join(lines)

    res_put = await vault_put_tool.coroutine(content=content, filename="logs.txt")
    pointer = res_put["vault_pointer"]

    # Test Extract
    res_extract = await vault_extract_tool.coroutine(
        vault_pointer=pointer,
        keyword="SECRET_KEY",
        context_lines=1
    )

    assert res_extract["success"] is True
    extracted = res_extract["extracted_content"]
    assert "Line 49" in extracted
    assert "SECRET_KEY" in extracted
    assert "Line 51" in extracted
    assert "Line 0" not in extracted

@pytest.mark.asyncio
async def test_vault_extract_tool_regex(mock_context):
    content = "Revenue: $100\nCost: $50\nProfit: $50\n"
    res_put = await vault_put_tool.coroutine(content=content, filename="financials.txt")
    pointer = res_put["vault_pointer"]

    # Test Extract regex
    res_extract = await vault_extract_tool.coroutine(
        vault_pointer=pointer,
        regex_pattern=r"Profit.*",
        context_lines=0
    )

    assert res_extract["success"] is True
    extracted = res_extract["extracted_content"]
    assert "Profit: $50" in extracted
    assert "Revenue" not in extracted

@pytest.mark.asyncio
async def test_vault_extract_no_args(mock_context):
    res_extract = await vault_extract_tool.coroutine(vault_pointer="vault://test")
    assert res_extract["success"] is False
    assert "Must provide either" in res_extract["error"]
