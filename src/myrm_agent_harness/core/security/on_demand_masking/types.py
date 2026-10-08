"""Domain types for on-demand credential materialization and multi-encoding masking.

[INPUT]
- Credential field and provider specifications.

[OUTPUT]
- CredentialField, MaterializedCredential, MaskedExecutionResult, MaskedExecutionError.

[POS]
Domain value objects and execution contracts for credential materialization and masking.
"""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CredentialField:
    """Individual environment variable field produced by a credential."""

    key: str
    value: str
    is_secret: bool = True


@dataclass(frozen=True)
class MaterializedCredential:
    """Outcome of resolving a credential on demand."""

    handle: str
    fields: list[CredentialField] = field(default_factory=list)


@dataclass(frozen=True)
class MaskedExecutionResult:
    """Output of command execution with sensitive tokens masked."""

    stdout: str
    stderr: str
    exit_code: int
    masked_count: int
    redacted_labels: list[str] = field(default_factory=list)


class MaskedExecutionError(Exception):
    """Exception raised during execution with masked traceback and preserved exit code."""

    def __init__(
        self,
        message: str,
        exit_code: int | None = None,
        masked_traceback: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.masked_traceback = masked_traceback
