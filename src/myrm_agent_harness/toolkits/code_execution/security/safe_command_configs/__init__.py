"""Safe subcommand configurations for flag-level command validation.

Pure data module — defines which flags are safe for each command+subcommand.
The ``SUBCOMMAND_CONFIGS`` registry maps base commands (e.g. "git", "npm")
to their subcommand config dictionaries.

Consumers:
- ``risk_classifier.classify_command_risk()`` — auto-allow decisions
"""

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.containers import (
    DOCKER_SAFE_SUBCOMMANDS,
    KUBECTL_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.filesystem import (
    FIND_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.git import (
    GIT_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.go import (
    GO_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.javascript import (
    BUN_SAFE_SUBCOMMANDS,
    NPM_SAFE_SUBCOMMANDS,
    PNPM_SAFE_SUBCOMMANDS,
    YARN_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.python_pkg import (
    PIP_SAFE_SUBCOMMANDS,
    UV_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.rust import (
    CARGO_SAFE_SUBCOMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)

SUBCOMMAND_CONFIGS: dict[str, dict[str, SubcommandConfig]] = {
    "git": GIT_SAFE_SUBCOMMANDS,
    "npm": NPM_SAFE_SUBCOMMANDS,
    "npx": {},
    "bun": BUN_SAFE_SUBCOMMANDS,
    "bunx": {},
    "pnpm": PNPM_SAFE_SUBCOMMANDS,
    "yarn": YARN_SAFE_SUBCOMMANDS,
    "pip": PIP_SAFE_SUBCOMMANDS,
    "pip3": PIP_SAFE_SUBCOMMANDS,
    "uv": UV_SAFE_SUBCOMMANDS,
    "go": GO_SAFE_SUBCOMMANDS,
    "find": FIND_SAFE_SUBCOMMANDS,
    "docker": DOCKER_SAFE_SUBCOMMANDS,
    "kubectl": KUBECTL_SAFE_SUBCOMMANDS,
    "cargo": CARGO_SAFE_SUBCOMMANDS,
}

__all__ = [
    "SUBCOMMAND_CONFIGS",
    "FlagArgType",
    "SubcommandConfig",
]
