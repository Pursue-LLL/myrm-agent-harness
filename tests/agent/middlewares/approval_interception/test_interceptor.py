import asyncio
from typing import Any

import pytest
from langgraph.types import Command

from myrm_agent_harness.agent.middlewares.approval_interception.interceptor import (
    check_pending_approval,
    intercept_approval_text,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType


class MockTask:
    def __init__(self, interrupts: list[Any] | None = None):
        self.interrupts = interrupts or []


class MockState:
    def __init__(self, tasks: list[MockTask] | None = None):
        self.tasks = tasks or []


class MockCheckpointer:
    def __init__(self, state: MockState | None = None, should_fail: bool = False):
        self.state = state
        self.should_fail = should_fail

    async def aget_tuple(self, config: dict[str, Any]) -> MockState | None:
        if self.should_fail:
            raise Exception("Mock failure")
        return self.state


@pytest.mark.asyncio
class TestApprovalInterceptor:
    async def test_check_pending_approval_no_checkpointer(self):
        assert not await check_pending_approval(None, "thread_1")

    async def test_check_pending_approval_no_state(self):
        checkpointer = MockCheckpointer(state=None)
        assert not await check_pending_approval(checkpointer, "thread_1")

    async def test_check_pending_approval_no_tasks(self):
        checkpointer = MockCheckpointer(state=MockState(tasks=[]))
        assert not await check_pending_approval(checkpointer, "thread_1")

    async def test_check_pending_approval_no_interrupts(self):
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[])]))
        assert not await check_pending_approval(checkpointer, "thread_1")

    async def test_check_pending_approval_with_interrupts(self):
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[{"resume": "value"}])]))
        assert await check_pending_approval(checkpointer, "thread_1")

    async def test_check_pending_approval_exception(self):
        checkpointer = MockCheckpointer(should_fail=True)
        assert not await check_pending_approval(checkpointer, "thread_1")

    async def test_intercept_approval_text_already_command(self):
        query = Command(resume="approve")
        result = await intercept_approval_text(query, None, "thread_1", "msg_1", None)
        assert result is query

    async def test_intercept_approval_text_empty_query(self):
        query = ""
        result = await intercept_approval_text(query, None, "thread_1", "msg_1", None)
        assert result is query

    async def test_intercept_approval_text_not_pending(self):
        query = "yes"
        checkpointer = MockCheckpointer(state=MockState(tasks=[]))
        result = await intercept_approval_text(query, checkpointer, "thread_1", "msg_1", None)
        assert result is query

    async def test_intercept_approval_text_approve_intent(self):
        query = "yes"
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[{"resume": "value"}])]))
        output_queue = asyncio.Queue()

        result = await intercept_approval_text(query, checkpointer, "thread_1", "msg_1", output_queue)

        assert isinstance(result, Command)
        assert result.resume == {"decision": "approve"}

        assert output_queue.qsize() == 1
        event = await output_queue.get()
        assert event["type"] == AgentEventType.APPROVAL_INTERCEPTED.value
        assert event["data"]["decision"] == "approve"
        assert event["data"]["original_text"] == "yes"
        assert event["messageId"] == "msg_1"

    async def test_intercept_approval_text_reject_intent(self):
        query = "no"
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[{"resume": "value"}])]))
        output_queue = asyncio.Queue()

        result = await intercept_approval_text(query, checkpointer, "thread_1", "msg_1", output_queue)

        assert isinstance(result, Command)
        assert result.resume == {"decision": "reject"}

        assert output_queue.qsize() == 1
        event = await output_queue.get()
        assert event["type"] == AgentEventType.APPROVAL_INTERCEPTED.value
        assert event["data"]["decision"] == "reject"
        assert event["data"]["original_text"] == "no"
        assert event["messageId"] == "msg_1"

    async def test_intercept_approval_text_feedback_intent(self):
        query = "yes, but do it differently"
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[{"resume": "value"}])]))
        output_queue = asyncio.Queue()

        result = await intercept_approval_text(query, checkpointer, "thread_1", "msg_1", output_queue)

        assert isinstance(result, Command)
        assert result.resume == {"decision": "feedback", "feedback": "yes, but do it differently"}

        assert output_queue.qsize() == 1
        event = await output_queue.get()
        assert event["type"] == AgentEventType.APPROVAL_INTERCEPTED.value
        assert event["data"]["decision"] == "feedback"
        assert event["data"]["original_text"] == "yes, but do it differently"
        assert event["messageId"] == "msg_1"

    async def test_intercept_approval_text_list_query(self):
        query = [{"type": "text", "text": "yes"}]
        checkpointer = MockCheckpointer(state=MockState(tasks=[MockTask(interrupts=[{"resume": "value"}])]))
        output_queue = asyncio.Queue()

        result = await intercept_approval_text(query, checkpointer, "thread_1", "msg_1", output_queue)

        assert isinstance(result, Command)
        assert result.resume == {"decision": "approve"}

        assert output_queue.qsize() == 1
        event = await output_queue.get()
        assert event["type"] == AgentEventType.APPROVAL_INTERCEPTED.value
        assert event["data"]["decision"] == "approve"
        assert event["data"]["original_text"] == "yes"
        assert event["messageId"] == "msg_1"
