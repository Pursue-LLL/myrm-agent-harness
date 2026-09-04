"""Agent Secrets Backend Module.

[INPUT]
- .local_backend::LocalSecretBackend (POS: Local secret backend. Persists agent secrets as AES-256-GCM encrypted files on disk.)
- .memory_backend::InMemorySecretBackend (POS: In-memory secret backend for testing and ephemeral sessions.)
- .protocols::AgentSecretBackend (POS: Protocol for Agent Secret Storage Backend.)

[OUTPUT]
- AgentSecretBackend: Protocol for Agent Secret Storage Backend
- InMemorySecretBackend: In-memory secret backend for testing
- LocalSecretBackend: AES-256-GCM encrypted file persistent store
- SecretEncryptionError: Exception raised when secret encryption/decryption fails

[POS]
Agent secrets backend package entry point. Re-exports storage protocols and implementations.
"""

from .command_backend import CommandExecutionError, CommandSecretBackend
from .local_backend import LocalSecretBackend, SecretEncryptionError
from .memory_backend import InMemorySecretBackend
from .protocols import AgentSecretBackend

__all__ = [
    "AgentSecretBackend",
    "CommandExecutionError",
    "CommandSecretBackend",
    "InMemorySecretBackend",
    "LocalSecretBackend",
    "SecretEncryptionError",
]
