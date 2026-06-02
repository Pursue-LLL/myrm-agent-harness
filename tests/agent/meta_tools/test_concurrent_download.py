"""Tests for concurrent download functionality"""

import httpx
import pytest
import respx


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_download_success():
    """测试并发下载成功场景"""
    from myrm_agent_harness.agent.meta_tools.http.concurrent_download import concurrent_download

    # Mock 3 endpoints
    respx.get("https://api.test.com/file1.txt").mock(return_value=httpx.Response(200, text="File 1 content"))
    respx.get("https://api.test.com/file2.txt").mock(return_value=httpx.Response(200, text="File 2 content"))
    respx.get("https://api.test.com/file3.txt").mock(return_value=httpx.Response(200, text="File 3 content"))

    # Concurrent download
    results = await concurrent_download(
        urls=[
            "https://api.test.com/file1.txt",
            "https://api.test.com/file2.txt",
            "https://api.test.com/file3.txt",
        ],
        max_concurrency=2,
    )

    # Verify all success
    assert len(results) == 3
    assert all(r["status"] == "success" for r in results)
    assert all(r["error"] is None for r in results)
    assert all(r["size"] > 0 for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_download_partial_failure():
    """测试并发下载部分失败场景"""
    from myrm_agent_harness.agent.meta_tools.http.concurrent_download import concurrent_download

    # Mock 2 success, 1 failure
    respx.get("https://api.test.com/file1.txt").mock(return_value=httpx.Response(200, text="File 1 content"))
    respx.get("https://api.test.com/file2.txt").mock(return_value=httpx.Response(404, text="Not found"))
    respx.get("https://api.test.com/file3.txt").mock(return_value=httpx.Response(200, text="File 3 content"))

    # Concurrent download
    results = await concurrent_download(
        urls=[
            "https://api.test.com/file1.txt",
            "https://api.test.com/file2.txt",
            "https://api.test.com/file3.txt",
        ],
        max_concurrency=3,
    )

    # Verify partial failure
    assert len(results) == 3
    success_results = [r for r in results if r["status"] == "success"]
    failed_results = [r for r in results if r["status"] == "failed"]

    assert len(success_results) == 2
    assert len(failed_results) == 1
    assert failed_results[0]["error"] is not None


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_download_with_output_dir(tmp_path):
    """测试并发下载到文件"""
    from myrm_agent_harness.agent.meta_tools.http.concurrent_download import concurrent_download

    # Mock 2 endpoints
    respx.get("https://api.test.com/file1.txt").mock(return_value=httpx.Response(200, text="File 1 content"))
    respx.get("https://api.test.com/file2.txt").mock(return_value=httpx.Response(200, text="File 2 content"))

    # Concurrent download to tmp_path
    results = await concurrent_download(
        urls=[
            "https://api.test.com/file1.txt",
            "https://api.test.com/file2.txt",
        ],
        output_dir=str(tmp_path),
        max_concurrency=2,
    )

    # Verify files created
    assert len(results) == 2
    assert all(r["status"] == "success" for r in results)
    assert all(r["file_path"] is not None for r in results)

    # Verify file contents
    file1_path = tmp_path / "file1.txt"
    file2_path = tmp_path / "file2.txt"
    assert file1_path.exists()
    assert file2_path.exists()
    assert file1_path.read_text() == "File 1 content"
    assert file2_path.read_text() == "File 2 content"


@pytest.mark.asyncio
async def test_concurrent_download_empty_urls():
    """测试空URL列表"""
    from myrm_agent_harness.agent.meta_tools.http.concurrent_download import concurrent_download

    results = await concurrent_download(urls=[])
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_download_concurrency_limit():
    """测试并发度控制"""
    import asyncio

    from myrm_agent_harness.agent.meta_tools.http.concurrent_download import concurrent_download

    # Track concurrent requests
    concurrent_count = [0]
    max_concurrent = [0]

    async def mock_response(request):
        concurrent_count[0] += 1
        max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
        await asyncio.sleep(0.1)  # Simulate delay
        concurrent_count[0] -= 1
        return httpx.Response(200, text="OK")

    # Mock 5 endpoints
    for i in range(5):
        respx.get(f"https://api.test.com/file{i}.txt").mock(side_effect=mock_response)

    # Concurrent download with max_concurrency=2
    results = await concurrent_download(urls=[f"https://api.test.com/file{i}.txt" for i in range(5)], max_concurrency=2)

    # Verify concurrency limit
    assert len(results) == 5
    assert all(r["status"] == "success" for r in results)
    assert max_concurrent[0] <= 2, f"Max concurrent requests: {max_concurrent[0]} (expected <= 2)"
