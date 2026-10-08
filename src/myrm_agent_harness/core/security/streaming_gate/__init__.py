"""Streaming Endpoint Identity Gate Parity Package.

Enforces zero bypass on long-lived event streams (SSE, WebSocket, chunked HTTP),
ensuring parity with REST endpoint authentication, scopes, and resource bindings.
"""

from myrm_agent_harness.core.security.streaming_gate.evaluator import (
    StreamingIdentityGateEvaluator,
)
from myrm_agent_harness.core.security.streaming_gate.registry import (
    StreamingEndpointRegistry,
)
from myrm_agent_harness.core.security.streaming_gate.types import (
    GateDecision,
    StreamingAccessDeniedError,
    StreamingClientIdentity,
    StreamingEndpointContract,
    StreamingGateError,
    StreamingGateVerdict,
    StreamingParityAuditIssue,
    StreamingTransport,
)

__all__ = [
    "GateDecision",
    "StreamingAccessDeniedError",
    "StreamingClientIdentity",
    "StreamingEndpointContract",
    "StreamingEndpointRegistry",
    "StreamingGateError",
    "StreamingGateVerdict",
    "StreamingIdentityGateEvaluator",
    "StreamingParityAuditIssue",
    "StreamingTransport",
]
