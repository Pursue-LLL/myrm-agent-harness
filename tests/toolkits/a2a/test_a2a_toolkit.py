"""Tests for A2A toolkit models, security helpers, and protocols."""

from __future__ import annotations

import time

import pytest
from myrm_agent_harness.toolkits.a2a import (
    A2A_PROTOCOL_VERSION,
    WELL_KNOWN_AGENT_CARD_PATH,
    A2ATask,
    A2ATaskService,
    AgentCapabilities,
    AgentCard,
    AgentCardProvider,
    AgentInterface,
    AgentSkill,
    JsonRpcError,
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
    TaskArtifact,
    TaskMessage,
    TaskRole,
    TaskStatus,
    TransportProtocol,
    WebhookNotification,
    compute_hmac_signature,
    mask_secret,
    sanitize_bearer_token,
    verify_hmac_signature,
)


def test_a2a_protocol_constants() -> None:
    """Protocol version should be 1.0.0 and well-known path standard."""
    assert A2A_PROTOCOL_VERSION == "1.0.0"
    assert WELL_KNOWN_AGENT_CARD_PATH == "/.well-known/agent-card.json"


def test_agent_card_serialization() -> None:
    """AgentCard can serialize and deserialize with camelCase aliases."""
    skill = AgentSkill(
        id="code_review",
        name="Code Reviewer",
        description="Analyzes code changes",
        tags=["review", "audit"],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    )
    iface = AgentInterface(
        url="http://localhost:8080/api/v1/a2a/rpc",
        protocol_binding=TransportProtocol.JSONRPC,
    )
    card = AgentCard(
        name="TestAgent",
        description="A test specialist agent",
        supported_interfaces=[iface],
        skills=[skill],
        capabilities=AgentCapabilities(push_notifications=True),
    )

    dumped = card.model_dump(by_alias=True)
    assert dumped["name"] == "TestAgent"
    assert dumped["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert dumped["skills"][0]["inputModes"] == ["text/plain"]
    assert dumped["capabilities"]["pushNotifications"] is True

    parsed = AgentCard.model_validate(dumped)
    assert parsed.name == card.name
    assert len(parsed.skills) == 1
    assert parsed.skills[0].id == "code_review"


def test_a2a_task_lifecycle_models() -> None:
    """A2ATask models should represent status, messages, and artifacts."""
    now = time.time()
    task = A2ATask(
        task_id="t-123",
        status=TaskStatus.WORKING,
        messages=[
            TaskMessage(role=TaskRole.USER, content="Hello", timestamp=now),
            TaskMessage(role=TaskRole.AGENT, content="Hi there", timestamp=now + 1.0),
        ],
        artifacts=[
            TaskArtifact(name="report.txt", uri="file:///tmp/report.txt", mime_type="text/plain"),
        ],
        created_at=now,
        updated_at=now + 2.0,
        agent_id="code-expert",
        push_url="https://example.com/webhook",
    )

    dumped = task.model_dump(by_alias=True)
    assert dumped["taskId"] == "t-123"
    assert dumped["status"] == "working"
    assert dumped["messages"][0]["role"] == "user"
    assert dumped["artifacts"][0]["mimeType"] == "text/plain"
    assert dumped["agentId"] == "code-expert"

    restored = A2ATask.model_validate(dumped)
    assert restored.task_id == "t-123"
    assert restored.status == TaskStatus.WORKING
    assert len(restored.messages) == 2
    assert len(restored.artifacts) == 1


def test_json_rpc_models() -> None:
    """JSON-RPC 2.0 request and response models should serialize correctly."""
    req = JsonRpcRequest(
        method="tasks/send",
        params={"prompt": "Do work", "agentId": "expert"},
        id="req-1",
    )
    req_dict = req.model_dump()
    assert req_dict["jsonrpc"] == "2.0"
    assert req_dict["method"] == "tasks/send"
    assert req_dict["id"] == "req-1"

    res_ok = JsonRpcResponse(result={"taskId": "t-1"}, id="req-1")
    assert res_ok.jsonrpc == "2.0"
    assert res_ok.result == {"taskId": "t-1"}
    assert res_ok.error is None

    res_err = JsonRpcResponse(
        error=JsonRpcError(code=int(JsonRpcErrorCode.TASK_NOT_FOUND), message="Task not found"),
        id="req-2",
    )
    assert res_err.error is not None
    assert res_err.error.code == -32004
    assert res_err.error.message == "Task not found"


def test_webhook_notification_model() -> None:
    """WebhookNotification should encapsulate delivery_id, event, and A2ATask."""
    now = time.time()
    task = A2ATask(
        task_id="t-456",
        status=TaskStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    webhook = WebhookNotification(
        delivery_id="del-789",
        event="task.completed",
        timestamp=now,
        task=task,
    )
    data = webhook.model_dump(by_alias=True)
    assert data["deliveryId"] == "del-789"
    assert data["event"] == "task.completed"
    assert data["task"]["taskId"] == "t-456"


def test_security_hmac_computation_and_verification() -> None:
    """HMAC computation and verification with timestamp guard."""
    secret = "my-secret-key-12345"
    body = '{"taskId":"t-1","status":"completed"}'
    now = time.time()

    sig = compute_hmac_signature(secret, body, now)
    assert isinstance(sig, str)
    assert len(sig) == 64  # sha256 hex string

    # Valid verification
    assert verify_hmac_signature(secret, body, now, sig, tolerance_sec=300.0, current_time=now)

    # Tampered body fails
    assert not verify_hmac_signature(
        secret, body + "x", now, sig, tolerance_sec=300.0, current_time=now
    )

    # Wrong secret fails
    assert not verify_hmac_signature(
        "wrong-secret", body, now, sig, tolerance_sec=300.0, current_time=now
    )

    # Replay attack (timestamp outside tolerance window)
    assert not verify_hmac_signature(
        secret, body, now - 500.0, sig, tolerance_sec=300.0, current_time=now
    )

    # Invalid timestamp format
    assert not verify_hmac_signature(
        secret, body, "invalid-ts", sig, tolerance_sec=300.0, current_time=now
    )


def test_security_helpers() -> None:
    """Sanitize bearer tokens and mask secrets."""
    assert sanitize_bearer_token("Bearer abc123def") == "abc123def"
    assert sanitize_bearer_token("bearer secret_key_test") == "secret_key_test"
    assert sanitize_bearer_token("token123") == "token123"
    assert sanitize_bearer_token(None) is None

    assert mask_secret("abcdef123456") == "***3456"
    assert mask_secret("123") == "***"
    assert mask_secret(None) == "<none>"


def test_protocols_runtime_checkable() -> None:
    """Protocols should be runtime checkable."""

    class DummyProvider:
        async def get_card(self, agent_id: str | None = None) -> AgentCard:
            return AgentCard(name="A", description="B")

        async def get_extended_card(self, agent_id: str | None = None) -> AgentCard | None:
            return None

    class DummyTaskService:
        async def send_task(
            self,
            prompt: str,
            *,
            task_id: str | None = None,
            agent_id: str | None = None,
            push_url: str | None = None,
            push_secret: str | None = None,
        ) -> A2ATask:
            now = time.time()
            return A2ATask(task_id="t-1", created_at=now, updated_at=now)

        async def get_task(self, task_id: str) -> A2ATask | None:
            return None

        async def cancel_task(self, task_id: str) -> bool:
            return False

    assert isinstance(DummyProvider(), AgentCardProvider)
    assert isinstance(DummyTaskService(), A2ATaskService)
