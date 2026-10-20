"""Detect external (non-file) side effects in shell commands.

A workspace rollback restores files only. This detector names the commands whose
effects live outside the workspace (databases, containers and cloud, network
writes, published code) so the host can warn that a rollback will not undo them.

Only the command at the head of each pipeline segment is classified, so a word
that merely appears as an argument (``grep docker``, ``pip install docker``) or
inside a quoted string or heredoc body is not an effect.

[INPUT]
- .shell_command_strip::_strip_quoted_content (POS: single-quote content masking)

[OUTPUT]
- detect_external_effects: command -> effect categories ("database", "container_cloud", "network_mutation", "publish")

[POS]
Pure-function classifier for irreversible external effects in bash commands.
The local executor calls it before running a command and hands the result to the
execution interceptor, which decides what to do with it.
"""

from __future__ import annotations

import re

from .shell_command_strip import _strip_quoted_content

_CATEGORY_ORDER: tuple[str, ...] = ("database", "container_cloud", "network_mutation", "publish")

_DATABASE_COMMANDS: frozenset[str] = frozenset(
    {"psql", "mysql", "mysqldump", "mongo", "mongosh", "mongodump", "redis-cli", "sqlite3", "cqlsh", "influx"}
)

_CONTAINER_CLOUD_COMMANDS: frozenset[str] = frozenset(
    {
        "docker",
        "docker-compose",
        "podman",
        "kubectl",
        "helm",
        "terraform",
        "aws",
        "gcloud",
        "az",
        "flyctl",
        "heroku",
    }
)

# Prefixes that run the next word as the real command.
_TRANSPARENT_PREFIXES: frozenset[str] = frozenset({"sudo", "doas", "env", "time", "nohup", "nice", "command", "exec"})

_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")
_HEREDOC_RE = re.compile(r"((?<!<)<<-?\s*(['\"]?)(\w+)\2)([^\n]*)\n.*?\n[ \t]*\3[ \t]*(?:\n|$)", re.DOTALL)

_HTTP_MUTATION_RE = re.compile(r"curl\s+.*-X\s*(POST|PUT|DELETE|PATCH)", re.IGNORECASE)
_CURL_DATA_RE = re.compile(
    r"curl\s+.*(-d\s|--data\b|--data-raw\b|--data-binary\b|--data-urlencode\b|-F\s|--form\b)",
    re.IGNORECASE,
)
_WGET_POST_RE = re.compile(r"wget\s+.*--post", re.IGNORECASE)
_HTTPIE_MUTATION_RE = re.compile(r"\bhttps?\s+(POST|PUT|DELETE|PATCH)\s", re.IGNORECASE)

_GIT_PUSH_RE = re.compile(r"^git(?:\s+(?:-[Cc]\s+\S+|--?[\w-]+(?:=\S+)?))*\s+push(?=\s|$)")
_PUBLISH_RE = re.compile(
    r"^(?:(?:npm|pnpm|yarn|bun|cargo)\s+publish|twine\s+upload|gh\s+(?:pr\s+(?:create|merge)|release\s+create))(?=\s|$)"
)


def _drop_heredoc_bodies(command: str) -> str:
    """Remove heredoc payloads: their lines are data, not commands."""
    return _HEREDOC_RE.sub(lambda m: f"{m.group(1)}{m.group(4)}\n", command)


def _leading_words(segment: str) -> list[str]:
    """Words of a segment from its real command onward (env assignments and prefixes skipped)."""
    words = segment.split()
    start = 0
    while start < len(words):
        word = words[start]
        if _ENV_ASSIGNMENT_RE.match(word) or word in _TRANSPARENT_PREFIXES or (start > 0 and word.startswith("-")):
            start += 1
            continue
        break
    return words[start:]


def _base_name(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _classify_segment(segment: str) -> set[str]:
    words = _leading_words(segment)
    if not words:
        return set()

    head = _base_name(words[0])
    text = " ".join(words)
    effects: set[str] = set()

    if head in _DATABASE_COMMANDS:
        effects.add("database")
    elif head in _CONTAINER_CLOUD_COMMANDS:
        effects.add("container_cloud")
        # `docker exec db psql ...` / `kubectl exec pod -- psql ...` run the client inside the container.
        if any(_base_name(word) in _DATABASE_COMMANDS for word in words[1:]):
            effects.add("database")
    elif (
        (head == "curl" and (_HTTP_MUTATION_RE.search(text) or _CURL_DATA_RE.search(text)))
        or (head == "wget" and _WGET_POST_RE.search(text))
        or (head in ("http", "https") and _HTTPIE_MUTATION_RE.search(text))
    ):
        effects.add("network_mutation")
    elif _GIT_PUSH_RE.match(text) or _PUBLISH_RE.match(text):
        effects.add("publish")

    return effects


def detect_external_effects(command: str) -> list[str]:
    """Return the external effect categories of ``command`` in a stable order (empty if none).

    Categories: "database", "container_cloud", "network_mutation", "publish".
    """
    if not command or not command.strip():
        return []

    masked = _strip_quoted_content(_drop_heredoc_bodies(command))
    found: set[str] = set()
    for segment in _SEGMENT_SPLIT_RE.split(masked):
        found |= _classify_segment(segment)

    return [category for category in _CATEGORY_ORDER if category in found]
