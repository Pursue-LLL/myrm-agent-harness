"""Workflow fingerprint calculation for cron automation prerequisite gating.

Pure deterministic functions — no I/O, safe to import anywhere in harness and server.
Used to uniquely identify automation workflows across manual chat/kanban runs and cron definitions.

[INPUT]
- prompt: str | None (Task prompt or query)
- agent_id: str | None (Bound agent identifier)
- workflow_template_id: str | None (Bound workflow template)
- command: str | None (Optional shell/script command)
- tools_allowed: tuple[str, ...] | list[str] | None (Allowed tools whitelist)

[OUTPUT]
- canonicalize_text: Normalizes whitespace and case for stable hashing
- compute_workflow_fingerprint: Computes SHA256 hex digest of the normalized workflow identity

[POS]
Harness-level domain algorithm for workflow identity and manual-run prerequisite verification.
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence


def canonicalize_text(text: str | None) -> str:
    """Canonicalize text by collapsing whitespace and trimming.

    Preserves case for case-sensitive parameters (e.g. commands/prompts)
    while eliminating formatting artifacts like variable spaces and newlines.
    """
    if not text:
        return ""
    # Normalize unicode whitespace and collapse multiple spaces/newlines into a single space
    collapsed = re.sub(r"\s+", " ", text.strip())
    return collapsed


def compute_workflow_fingerprint(
    *,
    prompt: str | None = None,
    agent_id: str | None = None,
    workflow_template_id: str | None = None,
    command: str | None = None,
    tools_allowed: Sequence[str] | None = None,
) -> str:
    """Compute a deterministic SHA-256 fingerprint for a workflow specification.

    Args:
        prompt: Task prompt or query text.
        agent_id: Agent identifier (defaulting to '__default__' if None).
        workflow_template_id: Workflow template ID if template-based.
        command: Command string if shell/script based.
        tools_allowed: Sequence of allowed tools (will be sorted for determinism).

    Returns:
        Hex-encoded SHA-256 string (64 characters).
    """
    canon_prompt = canonicalize_text(prompt)
    canon_agent = (agent_id or "__default__").strip().lower()
    canon_template = (workflow_template_id or "").strip()
    canon_cmd = canonicalize_text(command)

    if tools_allowed:
        sorted_tools = ",".join(sorted(t.strip() for t in tools_allowed if t.strip()))
    else:
        sorted_tools = ""

    # Construct standard deterministic canonical representation
    raw_signature = f"agent:{canon_agent}|tmpl:{canon_template}|tools:{sorted_tools}|cmd:{canon_cmd}|prompt:{canon_prompt}"
    return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()


__all__ = ["canonicalize_text", "compute_workflow_fingerprint"]
