"""Agent Plugins packaging rules — single source of truth for the parse and write sides.

The parser, the bundle writer and the business layer must agree on the same
name predicate, path-exclusion rule, namespace layout and capacity ceilings.
Keeping them in one module prevents the three copies from drifting apart
(a package that the writer emits must always be accepted by the parser).

[INPUT]
-- (none)

[OUTPUT]
-- MYRM_NAMESPACE / MYRM_AGENTS_DIR / MYRM_WORKSPACE_DIR: client-specific
   extension namespace (spec §8) and its directory layout.
-- is_valid_plugin_name / ascii_slug / plugin_identity: plugin name predicate and
   ASCII package identity derivation (display names never collapse).
-- is_excluded_path: archive paths that are never packaged or parsed.
-- AGENT_STRUCTURAL_KEYS: agent frontmatter keys owned by the format (everything else is client data).
-- MAX_*: capacity ceilings shared by import, export and persistence.

[POS]
Framework-level, client-agnostic plugin packaging rules (no I/O, no persistence).
"""

from __future__ import annotations

import hashlib
import re

# Spec §8: client-specific data lives under a reverse-domain namespace, both as
# an ``extensions`` key in plugin.json and as a same-named top-level directory.
MYRM_NAMESPACE = "ai.myrm"
MYRM_AGENTS_DIR = f"{MYRM_NAMESPACE}/agents"
MYRM_WORKSPACE_DIR = f"{MYRM_NAMESPACE}/workspace"

# Spec §5.5 name constraints plus a filesystem-safe length ceiling: the name is
# used as a directory segment when bundled files are persisted.
MAX_PLUGIN_NAME_LENGTH = 64
_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

# Capacity ceilings shared by the upload API, the template-file persistence and
# the exporter (a package the exporter emits must stay importable).
MAX_PLUGIN_ZIP_BYTES = 20 * 1024 * 1024
MAX_TEMPLATE_FILE_BYTES = 1 * 1024 * 1024
MAX_TOTAL_TEMPLATE_BYTES = 5 * 1024 * 1024

_EXCLUDED_SEGMENTS = frozenset({".git", ".venv", "__pycache__", "node_modules", ".DS_Store", "__MACOSX"})

# Agent frontmatter keys the format itself reads (they map onto ``PluginAgent``
# fields, including the aliases the parser accepts). Every other key is client
# data: the writer refuses to let client metadata shadow these, and a consumer
# can tell which declarations of a package it does not understand.
AGENT_STRUCTURAL_KEYS = frozenset(
    {
        "name",
        "description",
        "max_iterations",
        "max_iters",
        "skills",
        "skill_names",
        "tools",
        "tool_names",
        "mcps",
        "mcp_names",
        "subagents",
        "subagent_names",
        "is_subagent",
        "slug",
    }
)

# Longest ASCII prefix kept in a hashed identity (leaves room for "-" + 8 hex).
_IDENTITY_PREFIX_MAX = 40
_IDENTITY_DIGEST_LEN = 8
_LOSSLESS_RE = re.compile(r"^[a-z0-9._\s-]+$")


def is_valid_plugin_name(name: str) -> bool:
    """True when ``name`` is a valid plugin name (spec §5.5, ≤ 64 characters)."""
    return bool(name) and len(name) <= MAX_PLUGIN_NAME_LENGTH and _NAME_RE.match(name) is not None


def ascii_slug(raw: str) -> str:
    """Lossy ASCII slug of ``raw`` (lowercase alphanumerics, dots and hyphens)."""
    cleaned = raw.strip().lower()
    cleaned = re.sub(r"[_\s]+", "-", cleaned)
    cleaned = re.sub(r"[^a-z0-9.-]", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    return cleaned.strip(".-")


def plugin_identity(display_name: str, *, fallback: str = "myrm-plugin") -> str:
    """Derive a stable, valid package identity from a human display name.

    An already-ASCII name maps to its plain slug. A name that loses characters
    in the slug (CJK, emoji, accents) gets ``<ascii prefix>-<8 hex of sha256>``
    so different display names never collapse into the same package id.
    """
    slug = ascii_slug(display_name)
    lossless = _LOSSLESS_RE.match(display_name.strip().lower()) is not None
    if lossless and is_valid_plugin_name(slug):
        return slug

    prefix = slug[:_IDENTITY_PREFIX_MAX].strip(".-") or fallback
    digest = hashlib.sha256(display_name.strip().encode("utf-8")).hexdigest()[:_IDENTITY_DIGEST_LEN]
    return f"{prefix}-{digest}"


def is_excluded_path(path: str) -> bool:
    """True for archive paths that are neither parsed nor packaged.

    Dot-prefixed segments (``.git``, ``.env``, ``.DS_Store`` …) and well-known
    build/VCS directories are excluded on both sides of the round trip.
    """
    return any(part.startswith(".") or part in _EXCLUDED_SEGMENTS for part in path.split("/"))
