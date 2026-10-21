"""A2A (Agent-to-Agent) protocol support.

Provides data models, client resolver, cryptographic helpers, outbound A2A client,
delegation tools, and protocol contracts for Google's A2A v1.0 standard.
"""

from myrm_agent_harness.toolkits.a2a.client import (
    A2AClient,
    A2AClientError,
    A2ARpcError,
    A2ASSRFBlockedError,
)
from myrm_agent_harness.toolkits.a2a.protocols import (
    A2ATaskService,
    AgentCardProvider,
)
from myrm_agent_harness.toolkits.a2a.resolver import (
    A2ACardResolver,
    A2AResolveError,
    SSRFBlockedError,
)
from myrm_agent_harness.toolkits.a2a.security import (
    compute_hmac_signature,
    mask_secret,
    sanitize_bearer_token,
    verify_hmac_signature,
)
from myrm_agent_harness.toolkits.a2a.tools import (
    A2ACallInput,
    A2AOrchestrateInput,
    FanoutMode,
    execute_a2a_call,
    execute_a2a_orchestrate,
)
from myrm_agent_harness.toolkits.a2a.types import (
    A2A_PROTOCOL_VERSION,
    WELL_KNOWN_AGENT_CARD_PATH,
    A2ATask,
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
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
)

__all__ = [
    "A2A_PROTOCOL_VERSION",
    "WELL_KNOWN_AGENT_CARD_PATH",
    "A2ACallInput",
    "A2ACardResolver",
    "A2AClient",
    "A2AClientError",
    "A2AOrchestrateInput",
    "A2AResolveError",
    "A2ARpcError",
    "A2ASSRFBlockedError",
    "A2ATask",
    "A2ATaskService",
    "AgentCapabilities",
    "AgentCard",
    "AgentCardProvider",
    "AgentExtension",
    "AgentInterface",
    "AgentProvider",
    "AgentSkill",
    "FanoutMode",
    "JsonRpcError",
    "JsonRpcErrorCode",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "SSRFBlockedError",
    "TaskArtifact",
    "TaskMessage",
    "TaskRole",
    "TaskStatus",
    "TransportProtocol",
    "WebhookNotification",
    "compute_hmac_signature",
    "execute_a2a_call",
    "execute_a2a_orchestrate",
    "mask_secret",
    "sanitize_bearer_token",
    "verify_hmac_signature",
]
