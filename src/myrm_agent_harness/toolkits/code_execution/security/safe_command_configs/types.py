"""Safe subcommand configuration types.

Pure type definitions — no logic, no dependencies.

[INPUT]
- (none)

[OUTPUT]
- FlagArgType: Expected argument type for a safe flag.
- SubcommandConfig: Whitelist config for a specific command+subcommand combin...

[POS]
Safe subcommand configuration types.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class FlagArgType(StrEnum):
    """Expected argument type for a safe flag."""

    NONE = "none"
    NUMBER = "number"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class SubcommandConfig:
    """Whitelist config for a specific command+subcommand combination.

    Attributes:
        safe_flags: Mapping of safe flag names to their argument types.
        is_positional_dangerous: Optional callback ``(positionals, seen_flags) -> bool``.
            ``positionals`` are all non-flag tokens after flag parsing.
            ``seen_flags`` are the flag names (without values) that were parsed.
            Returns True if the positional args indicate a write/destructive operation.
        respects_double_dash: Whether the tool respects POSIX ``--``
            end-of-options. Default True (most tools do).
    """

    safe_flags: dict[str, FlagArgType] = field(default_factory=dict)
    is_positional_dangerous: Callable[[list[str], frozenset[str]], bool] | None = None
    respects_double_dash: bool = True
