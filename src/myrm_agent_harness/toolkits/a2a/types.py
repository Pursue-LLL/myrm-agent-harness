"""A2A (Agent-to-Agent) protocol data models.

Pydantic frozen models aligned with the Google A2A spec.
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

[POS]
A2A protocol type definitions. Provides all Agent-to-Agent protocol
data structures for agent discovery and capability declaration.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TransportProtocol(StrEnum):
    """Transport protocols for A2A communication."""

    JSONRPC = "JSONRPC"
    GRPC = "GRPC"
    HTTP_JSON = "HTTP+JSON"


# A2A spec 当前稳定版本
A2A_PROTOCOL_VERSION = "0.2.2"

# 标准 well-known 路径
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"


# ---------------------------------------------------------------------------
# Data Models (frozen Pydantic models)
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
