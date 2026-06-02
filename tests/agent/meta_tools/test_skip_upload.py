"""Tests for skip upload helper (fast upload optimization)"""

import httpx
import pytest
import respx


@pytest.mark.asyncio
@respx.mock
async def test_check_file_exists_by_md5_match():
    """测试文件存在且MD5匹配（可跳过上传）"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import calculate_md5, check_file_exists_by_md5

    file_content = b"Hello, world!"
    md5_hash = calculate_md5(file_content)

    # Mock HEAD endpoint with matching MD5
    respx.head("https://upload.example.com/file.txt").mock(
        return_value=httpx.Response(200, headers={"Content-MD5": md5_hash})
    )

    # Check if file exists
    can_skip = await check_file_exists_by_md5(url="https://upload.example.com/file.txt", file_content=file_content)

    assert can_skip is True  # Can skip upload (MD5 matches)


@pytest.mark.asyncio
@respx.mock
async def test_check_file_exists_by_md5_mismatch():
    """测试文件存在但MD5不匹配（需要上传）"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import calculate_md5, check_file_exists_by_md5

    file_content = b"Hello, world!"
    calculate_md5(file_content)

    # Mock HEAD endpoint with different MD5
    respx.head("https://upload.example.com/file.txt").mock(
        return_value=httpx.Response(200, headers={"Content-MD5": "different-md5-hash"})
    )

    # Check if file exists
    can_skip = await check_file_exists_by_md5(url="https://upload.example.com/file.txt", file_content=file_content)

    assert can_skip is False  # Cannot skip upload (MD5 mismatch)


@pytest.mark.asyncio
@respx.mock
async def test_check_file_exists_by_md5_not_found():
    """测试文件不存在（需要上传）"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import check_file_exists_by_md5

    file_content = b"Hello, world!"

    # Mock HEAD endpoint with 404 (file not found)
    respx.head("https://upload.example.com/file.txt").mock(return_value=httpx.Response(404))

    # Check if file exists
    can_skip = await check_file_exists_by_md5(url="https://upload.example.com/file.txt", file_content=file_content)

    assert can_skip is False  # Cannot skip upload (file not found)


@pytest.mark.asyncio
@respx.mock
async def test_check_file_exists_by_md5_no_md5_header():
    """测试文件存在但无MD5头（需要上传）"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import check_file_exists_by_md5

    file_content = b"Hello, world!"

    # Mock HEAD endpoint without MD5 header
    respx.head("https://upload.example.com/file.txt").mock(return_value=httpx.Response(200))

    # Check if file exists
    can_skip = await check_file_exists_by_md5(url="https://upload.example.com/file.txt", file_content=file_content)

    assert can_skip is False  # Cannot skip upload (no MD5 header)


@pytest.mark.asyncio
@respx.mock
async def test_check_file_exists_by_md5_etag():
    """测试使用ETag头作为MD5（可跳过上传）"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import calculate_md5, check_file_exists_by_md5

    file_content = b"Hello, world!"
    md5_hash = calculate_md5(file_content)

    # Mock HEAD endpoint with ETag (MD5)
    respx.head("https://upload.example.com/file.txt").mock(
        return_value=httpx.Response(200, headers={"ETag": f'"{md5_hash}"'})
    )

    # Check if file exists
    can_skip = await check_file_exists_by_md5(url="https://upload.example.com/file.txt", file_content=file_content)

    assert can_skip is True  # Can skip upload (ETag MD5 matches)


@pytest.mark.asyncio
async def test_calculate_md5():
    """测试MD5计算"""
    from myrm_agent_harness.agent.meta_tools.http.skip_upload_helper import calculate_md5

    # Known MD5 hash
    content = b"Hello, world!"
    expected_md5 = "6cd3556deb0da54bca060b4c39479839"

    actual_md5 = calculate_md5(content)
    assert actual_md5 == expected_md5
