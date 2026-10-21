"""Container ecosystem safe subcommand configurations (docker, kubectl).

Only read-only / inspection subcommands are included. Write operations
(docker run, kubectl apply, etc.) remain UNKNOWN → ASK.

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Container ecosystem safe subcommand configurations (docker, kubectl).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)

# ---------------------------------------------------------------------------
# docker
# ---------------------------------------------------------------------------

DOCKER_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "ps": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--last": FlagArgType.NUMBER,
            "-n": FlagArgType.NUMBER,
            "--latest": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--no-trunc": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--size": FlagArgType.NONE,
            "-s": FlagArgType.NONE,
        },
    ),
    "images": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--digests": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--no-trunc": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
        },
    ),
    "logs": SubcommandConfig(
        safe_flags={
            "--follow": FlagArgType.NONE,
            "-f": FlagArgType.NONE,
            "--since": FlagArgType.STRING,
            "--until": FlagArgType.STRING,
            "--tail": FlagArgType.STRING,
            "-n": FlagArgType.STRING,
            "--timestamps": FlagArgType.NONE,
            "-t": FlagArgType.NONE,
            "--details": FlagArgType.NONE,
        },
    ),
    "inspect": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--size": FlagArgType.NONE,
            "-s": FlagArgType.NONE,
            "--type": FlagArgType.STRING,
        },
    ),
    "stats": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--format": FlagArgType.STRING,
            "--no-stream": FlagArgType.NONE,
            "--no-trunc": FlagArgType.NONE,
        },
    ),
    "top": SubcommandConfig(safe_flags={}),
    "port": SubcommandConfig(safe_flags={}),
    "info": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
        },
    ),
    "version": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
        },
    ),
    "network ls": SubcommandConfig(
        safe_flags={
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--no-trunc": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
        },
    ),
    "network inspect": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--verbose": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
    ),
    "volume ls": SubcommandConfig(
        safe_flags={
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
        },
    ),
    "volume inspect": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
        },
    ),
    "image ls": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--digests": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--no-trunc": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
        },
    ),
    "image inspect": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
        },
    ),
    "container ls": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--format": FlagArgType.STRING,
            "--last": FlagArgType.NUMBER,
            "-n": FlagArgType.NUMBER,
            "--latest": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--no-trunc": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--size": FlagArgType.NONE,
            "-s": FlagArgType.NONE,
        },
    ),
    "container inspect": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "-f": FlagArgType.STRING,
            "--size": FlagArgType.NONE,
            "-s": FlagArgType.NONE,
        },
    ),
    "container logs": SubcommandConfig(
        safe_flags={
            "--follow": FlagArgType.NONE,
            "-f": FlagArgType.NONE,
            "--since": FlagArgType.STRING,
            "--until": FlagArgType.STRING,
            "--tail": FlagArgType.STRING,
            "-n": FlagArgType.STRING,
            "--timestamps": FlagArgType.NONE,
            "-t": FlagArgType.NONE,
            "--details": FlagArgType.NONE,
        },
    ),
    "compose ps": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--format": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
            "--status": FlagArgType.STRING,
            "--services": FlagArgType.NONE,
        },
    ),
    "compose logs": SubcommandConfig(
        safe_flags={
            "--follow": FlagArgType.NONE,
            "-f": FlagArgType.NONE,
            "--since": FlagArgType.STRING,
            "--until": FlagArgType.STRING,
            "--tail": FlagArgType.STRING,
            "-n": FlagArgType.STRING,
            "--timestamps": FlagArgType.NONE,
            "-t": FlagArgType.NONE,
            "--no-color": FlagArgType.NONE,
            "--no-log-prefix": FlagArgType.NONE,
        },
    ),
    "compose config": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--resolve-image-digests": FlagArgType.NONE,
            "--no-interpolate": FlagArgType.NONE,
            "--services": FlagArgType.NONE,
            "--volumes": FlagArgType.NONE,
            "--profiles": FlagArgType.NONE,
            "--images": FlagArgType.NONE,
        },
    ),
    "compose images": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
        },
    ),
    "compose top": SubcommandConfig(safe_flags={}),
    "compose ls": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--format": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
        },
    ),
    "compose version": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "--short": FlagArgType.NONE,
        },
    ),
    "compose build": SubcommandConfig(
        safe_flags={
            "--no-cache": FlagArgType.NONE,
            "--pull": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--progress": FlagArgType.STRING,
            "--parallel": FlagArgType.NONE,
        },
    ),
}

# ---------------------------------------------------------------------------
# kubectl
# ---------------------------------------------------------------------------

_KUBECTL_OUTPUT: dict[str, FlagArgType] = {
    "-o": FlagArgType.STRING,
    "--output": FlagArgType.STRING,
    "--no-headers": FlagArgType.NONE,
    "-w": FlagArgType.NONE,
    "--watch": FlagArgType.NONE,
    "--watch-only": FlagArgType.NONE,
    "--show-labels": FlagArgType.NONE,
    "--sort-by": FlagArgType.STRING,
}

_KUBECTL_NS: dict[str, FlagArgType] = {
    "-n": FlagArgType.STRING,
    "--namespace": FlagArgType.STRING,
    "-A": FlagArgType.NONE,
    "--all-namespaces": FlagArgType.NONE,
}

KUBECTL_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "get": SubcommandConfig(
        safe_flags={
            **_KUBECTL_OUTPUT,
            **_KUBECTL_NS,
            "-l": FlagArgType.STRING,
            "--selector": FlagArgType.STRING,
            "--field-selector": FlagArgType.STRING,
            "--chunk-size": FlagArgType.NUMBER,
        },
    ),
    "describe": SubcommandConfig(
        safe_flags={
            **_KUBECTL_NS,
            "-l": FlagArgType.STRING,
            "--selector": FlagArgType.STRING,
            "--show-events": FlagArgType.NONE,
        },
    ),
    "logs": SubcommandConfig(
        safe_flags={
            **_KUBECTL_NS,
            "-f": FlagArgType.NONE,
            "--follow": FlagArgType.NONE,
            "-p": FlagArgType.NONE,
            "--previous": FlagArgType.NONE,
            "--since": FlagArgType.STRING,
            "--since-time": FlagArgType.STRING,
            "--tail": FlagArgType.NUMBER,
            "--timestamps": FlagArgType.NONE,
            "-c": FlagArgType.STRING,
            "--container": FlagArgType.STRING,
            "--all-containers": FlagArgType.NONE,
            "-l": FlagArgType.STRING,
            "--selector": FlagArgType.STRING,
            "--max-log-requests": FlagArgType.NUMBER,
            "--prefix": FlagArgType.NONE,
        },
    ),
    "explain": SubcommandConfig(
        safe_flags={
            "--recursive": FlagArgType.NONE,
            "--api-version": FlagArgType.STRING,
        },
    ),
    "api-resources": SubcommandConfig(
        safe_flags={
            "-o": FlagArgType.STRING,
            "--output": FlagArgType.STRING,
            "--namespaced": FlagArgType.NONE,
            "--verbs": FlagArgType.STRING,
            "--api-group": FlagArgType.STRING,
            "--sort-by": FlagArgType.STRING,
            "--no-headers": FlagArgType.NONE,
        },
    ),
    "api-versions": SubcommandConfig(safe_flags={}),
    "version": SubcommandConfig(
        safe_flags={
            "--client": FlagArgType.NONE,
            "-o": FlagArgType.STRING,
            "--output": FlagArgType.STRING,
            "--short": FlagArgType.NONE,
        },
    ),
    "top pod": SubcommandConfig(
        safe_flags={
            **_KUBECTL_NS,
            "--containers": FlagArgType.NONE,
            "-l": FlagArgType.STRING,
            "--selector": FlagArgType.STRING,
            "--sort-by": FlagArgType.STRING,
            "--no-headers": FlagArgType.NONE,
        },
    ),
    "top node": SubcommandConfig(
        safe_flags={
            "--sort-by": FlagArgType.STRING,
            "--no-headers": FlagArgType.NONE,
            "-l": FlagArgType.STRING,
            "--selector": FlagArgType.STRING,
        },
    ),
    "cluster-info": SubcommandConfig(safe_flags={}),
    "config view": SubcommandConfig(
        safe_flags={
            "--minify": FlagArgType.NONE,
            "--raw": FlagArgType.NONE,
            "--flatten": FlagArgType.NONE,
            "-o": FlagArgType.STRING,
            "--output": FlagArgType.STRING,
        },
    ),
    "config current-context": SubcommandConfig(safe_flags={}),
    "config get-contexts": SubcommandConfig(
        safe_flags={
            "-o": FlagArgType.STRING,
            "--output": FlagArgType.STRING,
            "--no-headers": FlagArgType.NONE,
        },
    ),
}
