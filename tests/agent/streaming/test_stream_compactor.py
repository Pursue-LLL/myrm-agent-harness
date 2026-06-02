import asyncio

import pytest

from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
from myrm_agent_harness.agent.streaming.types import AgentEventType


@pytest.mark.asyncio
async def test_stream_compactor_basic():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    # Put multiple small chunks
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1"})
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "b", "messageId": "1"})
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "c", "messageId": "1"})

    # Queue should be empty because it's buffered
    assert queue.empty()

    # Put a non-message event, should flush
    await compactor.put({"type": AgentEventType.STATUS.value, "data": "status"})

    # Queue should have 2 items: the merged message, and the status
    assert queue.qsize() == 2
    msg = await queue.get()
    assert msg["type"] == AgentEventType.MESSAGE.value
    assert msg["data"] == "abc"
    assert msg["messageId"] == "1"

    status = await queue.get()
    assert status["type"] == AgentEventType.STATUS.value
    assert status["data"] == "status"


@pytest.mark.asyncio
async def test_stream_compactor_size_limit():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=5)

    # Put 6 chars
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "123", "messageId": "1"})
    assert queue.empty()
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "456", "messageId": "1"})

    # Should flush because 6 >= 5
    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg["data"] == "123456"
    assert compactor._buffer_size == 0


@pytest.mark.asyncio
async def test_stream_compactor_watchdog():
    queue = asyncio.Queue()
    # 极短的超时时间用于测试看门狗
    compactor = StreamCompactor(queue, max_wait_ms=50, max_chars=100)

    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1"})
    assert queue.empty()

    # 等待看门狗触发 (50ms + 缓冲)
    await asyncio.sleep(0.1)

    # 看门狗应该已经自动 flush 了缓冲区
    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg["data"] == "a"
    assert compactor._buffer_size == 0


@pytest.mark.asyncio
async def test_stream_compactor_artifact_content():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=100)

    await compactor.put({"type": AgentEventType.ARTIFACT_CONTENT.value, "data": "code1"})
    await compactor.put({"type": AgentEventType.ARTIFACT_CONTENT.value, "data": "code2"})

    assert queue.empty()

    # 显式 flush
    await compactor.flush()

    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg["type"] == AgentEventType.ARTIFACT_CONTENT.value
    assert msg["data"] == "code1code2"


@pytest.mark.asyncio
async def test_stream_compactor_event_type_switch():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=100)

    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "msg1"})
    # 切换事件类型，应该立即 flush 之前的 MESSAGE
    await compactor.put({"type": AgentEventType.ARTIFACT_CONTENT.value, "data": "art1"})

    assert queue.qsize() == 1
    msg1 = await queue.get()
    assert msg1["type"] == AgentEventType.MESSAGE.value
    assert msg1["data"] == "msg1"

    # 显式 flush ARTIFACT_CONTENT
    await compactor.flush()
    assert queue.qsize() == 1
    art1 = await queue.get()
    assert art1["type"] == AgentEventType.ARTIFACT_CONTENT.value
    assert art1["data"] == "art1"


@pytest.mark.asyncio
async def test_stream_compactor_metadata():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    await compactor.put(
        {"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1", "metadata": {"foo": "bar"}}
    )
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "b", "messageId": "1"})
    await compactor.flush()

    msg = await queue.get()
    assert msg["data"] == "ab"
    assert msg["metadata"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_stream_compactor_object():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1"})

    # Put an object (like STREAM_DONE)
    obj = object()
    await compactor.put(obj)

    assert queue.qsize() == 2
    msg = await queue.get()
    assert msg["data"] == "a"

    done = await queue.get()
    assert done is obj


@pytest.mark.asyncio
async def test_stream_compactor_empty_flush():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    # Empty flush should do nothing
    await compactor.flush()
    assert queue.empty()


@pytest.mark.asyncio
async def test_stream_compactor_watchdog_cancellation():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=100)

    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1"})
    assert compactor._watchdog_task is not None
    assert not compactor._watchdog_task.done()

    # Explicit flush should cancel the watchdog
    await compactor.flush()
    assert compactor._watchdog_task is None or compactor._watchdog_task.done()

    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg["data"] == "a"


@pytest.mark.asyncio
async def test_stream_compactor_not_dict_event():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "a", "messageId": "1"})

    # Put a non-dict event (e.g., a string or an object)
    await compactor.put("not a dict")

    # Should flush the buffer and put the non-dict event
    assert queue.qsize() == 2
    msg = await queue.get()
    assert msg["data"] == "a"

    non_dict = await queue.get()
    assert non_dict == "not a dict"


@pytest.mark.asyncio
async def test_stream_compactor_empty_data():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    # Put an event with empty data
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "", "messageId": "1"})

    # Should not buffer empty data, and since it's a target event but with empty data, it falls through to flush and put
    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg["data"] == ""


@pytest.mark.asyncio
async def test_stream_compactor_none_data():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=10)

    # Put an event with None data
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": None, "messageId": "1"})

    # None data is not buffered; event passes through AgentStreamEvent
    # which omits data=None from serialization (by design).
    assert queue.qsize() == 1
    msg = await queue.get()
    assert "data" not in msg or msg.get("data") is None

@pytest.mark.asyncio
async def test_compactor_reasoning_buffering():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=100)

    await compactor.put({"type": AgentEventType.REASONING.value, "data": "Thinking", "messageId": "msg-1"})
    await compactor.put({"type": AgentEventType.REASONING.value, "data": " about", "messageId": "msg-1"})
    await compactor.put({"type": AgentEventType.REASONING.value, "data": " it...", "messageId": "msg-1"})

    assert queue.empty()

    await compactor.flush()

    assert queue.qsize() == 1
    event = await queue.get()
    assert event["type"] == AgentEventType.REASONING.value
    assert event["data"] == "Thinking about it..."
    assert event["messageId"] == "msg-1"

@pytest.mark.asyncio
async def test_compactor_mixed_message_and_reasoning():
    queue = asyncio.Queue()
    compactor = StreamCompactor(queue, max_wait_ms=5000, max_chars=100)

    await compactor.put({"type": AgentEventType.REASONING.value, "data": "Thinking...", "messageId": "msg-1"})
    await compactor.put({"type": AgentEventType.MESSAGE.value, "data": "Hello", "messageId": "msg-1"})

    assert queue.qsize() == 1
    event1 = await queue.get()
    assert event1["type"] == AgentEventType.REASONING.value
    assert event1["data"] == "Thinking..."

    await compactor.flush()

    assert queue.qsize() == 1
    event2 = await queue.get()
    assert event2["type"] == AgentEventType.MESSAGE.value
    assert event2["data"] == "Hello"
