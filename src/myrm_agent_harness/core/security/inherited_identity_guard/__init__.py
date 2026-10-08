"""Inherited identity guard module for terminal and session isolation."""

from .sanitizer import (
    DEFAULT_DENIED_ENV_KEYS,
    STANDARD_SYSTEM_ENV_KEYS,
    InheritedIdentitySanitizer,
)
from .types import (
    AgentResumePlan,
    AgentSessionRef,
    AgentSessionRefKind,
    PersistedAgentSession,
    SanitizationPolicy,
    SanitizationResult,
)
from .validator import (
    MAX_RESUME_ARGS,
    MAX_RESUME_ARGV_BYTES,
    MAX_SESSION_ID_LEN,
    MAX_SESSION_PATH_LEN,
    OFFICIAL_SOURCE_PAIRS,
    VALID_START_SOURCES,
    is_official_agent_source,
    is_valid_session_id,
    is_valid_session_path,
    normalize_session_start_source,
    validate_resume_argv,
)

__all__ = [
    "DEFAULT_DENIED_ENV_KEYS",
    "MAX_RESUME_ARGS",
    "MAX_RESUME_ARGV_BYTES",
    "MAX_SESSION_ID_LEN",
    "MAX_SESSION_PATH_LEN",
    "OFFICIAL_SOURCE_PAIRS",
    "STANDARD_SYSTEM_ENV_KEYS",
    "VALID_START_SOURCES",
    "AgentResumePlan",
    "AgentSessionRef",
    "AgentSessionRefKind",
    "InheritedIdentitySanitizer",
    "PersistedAgentSession",
    "SanitizationPolicy",
    "SanitizationResult",
    "is_official_agent_source",
    "is_valid_session_id",
    "is_valid_session_path",
    "normalize_session_start_source",
    "validate_resume_argv",
]
