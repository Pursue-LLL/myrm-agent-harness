"""Detect external (non-file) side effects in shell commands.

When a snapshot is created before a bash command, this module determines
whether the command will produce state changes that file-rollback alone
cannot undo (e.g. database mutations, HTTP writes, container operations).

[POS]
Pure-function detector for irreversible external effects in bash commands.
Used by SnapshotInterceptor to tag snapshots with external_effects metadata.
"""

from __future__ import annotations

import re

_DATABASE_COMMANDS: set[str] = {
    "psql", "mysql", "mysqldump", "mongo", "mongosh", "mongodump",
    "redis-cli", "sqlite3", "cqlsh", "influx",
}

_CONTAINER_CLOUD_COMMANDS: set[str] = {
    "docker", "podman", "kubectl", "helm", "terraform",
    "aws", "gcloud", "az", "flyctl", "heroku",
}

_HTTP_MUTATION_RE = re.compile(
    r"curl\s+.*-X\s*(POST|PUT|DELETE|PATCH)",
    re.IGNORECASE,
)

_WGET_POST_RE = re.compile(
    r"wget\s+.*--post",
    re.IGNORECASE,
)


def detect_external_effects(command: str) -> list[str]:
    """Detect external effects that file-rollback cannot undo.

    Returns a list of effect categories (empty if none detected).
    Categories: "database", "container_cloud", "network_mutation".
    """
    if not command:
        return []

    effects: list[str] = []

    words = command.split()
    base_commands = {w.rsplit("/", 1)[-1] for w in words if not w.startswith("-")}

    if base_commands & _DATABASE_COMMANDS:
        effects.append("database")

    if base_commands & _CONTAINER_CLOUD_COMMANDS:
        effects.append("container_cloud")

    if _HTTP_MUTATION_RE.search(command) or _WGET_POST_RE.search(command):
        effects.append("network_mutation")

    return effects
