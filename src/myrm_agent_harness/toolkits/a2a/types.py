"""A2A (Agent-to-Agent) protocol data models.

Pydantic frozen models aligned with Google A2A v1.0 spec and JSON-RPC 2.0.
Reference: a2a-go/a2a/agent.go

[INPUT]
no - Base type definition module

[OUTPUT]
- AgentCard: Agent identity and capability manifest
- AgentSkill: Declarative skill description
- AgentCapabilities: Optional capability flags
- AgentInterface: Transport endpoint declaration
- AgentProvider: Service provider metadata
- TransportProtocol: Transport protocol enum
- TaskStatus: Task lifecycle state enum
- TaskRole: Message role enum (user, agent)
- TaskMessage: Individual message in A2A task history
- TaskArtifact: Artifact output produced by A2A task
- A2ATask: Complete task record with status and artifacts
- JsonRpcRequest / JsonRpcResponse / JsonRpcError: JSON-RPC 2.0 protocol models
- WebhookNotification: Signed push event payload

[POS]
A2A protocol type definitions. Provides all Agent-to-Agent protocol
data structures for agent discovery, capability declaration, and task RPC.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------


class TransportProtocol(StrEnum):
    """Transport protocols for A2A communication."""

    JSONRPC = "JSONRPC"
    GRPC = "GRPC"
    HTTP_JSON = "HTTP+JSON"


class TaskStatus(StrEnum):
    """A2A Task execution lifecycle states."""

    PENDING = "pending"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRole(StrEnum):
    """Participant role in A2A task exchange."""

    USER = "user"
    AGENT = "agent"


class JsonRpcErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 and A2A-specific error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    UNAUTHORIZED = -32001
    TASK_NOT_FOUND = -32004
    RATE_LIMITED = -32029


# A2A spec 稳定版本
A2A_PROTOCOL_VERSION = "1.0.0"

# 标准 well-known 路径
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"


# ---------------------------------------------------------------------------
# Discovery & Capability Models
# ---------------------------------------------------------------------------


class AgentProvider(BaseModel, frozen=True):
    """Agent 的服务提供者信息。"""

    organization: str
    url: str = ""


class AgentSkill(BaseModel, frozen=True):
    """Agent 的单项技能声明。

    Orchestrator 可据此语义匹配最合适的 Agent。
    """

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(
        default_factory=list,
        alias="inputModes",
    )
    output_modes: list[str] = Field(
        default_factory=list,
        alias="outputModes",
    )

    model_config = {"populate_by_name": True}


class AgentExtension(BaseModel, frozen=True):
    """Agent 支持的协议扩展声明。"""

    uri: str = ""
    description: str = ""
    required: bool = False
    params: dict[str, object] | None = None


class AgentCapabilities(BaseModel, frozen=True):
    """Agent 的可选能力声明。"""

    streaming: bool = False
    push_notifications: bool = Field(
        default=False,
        alias="pushNotifications",
    )
    extended_agent_card: bool = Field(
        default=False,
        alias="extendedAgentCard",
    )
    extensions: list[AgentExtension] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AgentInterface(BaseModel, frozen=True):
    """传输端点声明：URL + 协议绑定。"""

    url: str
    protocol_binding: TransportProtocol = Field(
        alias="protocolBinding",
    )
    protocol_version: str = Field(
        default=A2A_PROTOCOL_VERSION,
        alias="protocolVersion",
    )
    tenant: str | None = None

    model_config = {"populate_by_name": True}


class AgentCard(BaseModel, frozen=True):
    """A2A AgentCard — Agent 的自描述清单。

    包含身份、能力、技能、传输接口和安全需求等元数据，
    是 Agent 被外部系统发现和调用的基础。
    """

    name: str
    description: str
    version: str = "1.0.0"

    # 传输接口
    supported_interfaces: list[AgentInterface] = Field(
        default_factory=list,
        alias="supportedInterfaces",
    )

    # 能力声明
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)

    # 技能列表
    skills: list[AgentSkill] = Field(default_factory=list)

    # 默认 I/O MIME 类型
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        alias="defaultInputModes",
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        alias="defaultOutputModes",
    )

    # 提供者信息
    provider: AgentProvider | None = None

    # 图标和文档链接
    icon_url: str | None = Field(default=None, alias="iconUrl")
    documentation_url: str | None = Field(default=None, alias="documentationUrl")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Task & Execution Models
# ---------------------------------------------------------------------------


class TaskMessage(BaseModel, frozen=True):
    """Single message in an A2A task history."""

    role: TaskRole
    content: str
    timestamp: float


class TaskArtifact(BaseModel, frozen=True):
    """Artifact produced during task execution."""

    name: str
    uri: str
    mime_type: str = Field(default="text/plain", alias="mimeType")
    description: str = ""

    model_config = {"populate_by_name": True}


class A2ATask(BaseModel, frozen=True):
    """A2A Task representation tracking async lifecycle and outputs."""

    task_id: str = Field(alias="taskId")
    status: TaskStatus = TaskStatus.PENDING
    messages: list[TaskMessage] = Field(default_factory=list)
    artifacts: list[TaskArtifact] = Field(default_factory=list)
    created_at: float = Field(alias="createdAt")
    updated_at: float = Field(alias="updatedAt")
    error: str | None = None
    agent_id: str | None = Field(default=None, alias="agentId")
    push_url: str | None = Field(default=None, alias="pushUrl")
    push_secret: str | None = Field(default=None, alias="pushSecret")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Models
# ---------------------------------------------------------------------------


class JsonRpcError(BaseModel, frozen=True):
    """Standard JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: object | None = None


class JsonRpcRequest(BaseModel, frozen=True):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, object] | None = None
    id: str | int | None = None


class JsonRpcResponse(BaseModel, frozen=True):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: object | None = None
    error: JsonRpcError | None = None
    id: str | int | None = None


# ---------------------------------------------------------------------------
# Webhook / Push Notification Models
# ---------------------------------------------------------------------------


class WebhookNotification(BaseModel, frozen=True):
    """HMAC-signed push notification delivered to caller webhook."""

    delivery_id: str = Field(alias="deliveryId")
    event: str
    timestamp: float
    task: A2ATask

    model_config = {"populate_by_name": True}
