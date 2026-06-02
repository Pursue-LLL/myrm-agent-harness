"""LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized exception handling."""

from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
    extract_retry_after,
    is_context_overflow,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import (
    FailoverReason,
    ProbePolicy,
    RecoverabilityLevel,
    get_probe_policy,
    should_allow_probe,
)
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError
from myrm_agent_harness.toolkits.llms.errors.resilient import resilient_llm_call

__all__ = [
    "ErrorKind",
    "FailoverReason",
    # Exceptions
    "MyrmLLMError",
    "ProbePolicy",
    "RecoverabilityLevel",
    "classify_error",
    # New three-layer system
    "classify_failover_reason",
    "extract_retry_after",
    "get_probe_policy",
    "is_context_overflow",
    # Resilient
    "resilient_llm_call",
    "should_allow_probe",
]
