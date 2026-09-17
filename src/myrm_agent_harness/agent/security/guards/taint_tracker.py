"""Taint Tracker — session-level information-flow tracking for tool outputs.

Tracks which tool categories have produced output in the current session,
and checks whether a tool call is safe given the accumulated taint labels.

Since the LLM is a black box, taint propagation is approximate: once a
tool produces tainted output, all subsequent tool calls to incompatible
sinks are escalated to ASK (require user approval) rather than blocked.

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- TaintLabel: source categories (EXTERNAL_NETWORK, SECRET)
- TaintTracker: session-level taint accumulator
- TAINT_SOURCES: tool name → TaintLabel mapping
- TAINT_SINK_POLICIES: sink tool name → set of blocked TaintLabels
- get_taint_tracker() / reset_taint_tracker(): ContextVar accessors

[POS]
Layer 2 enhancement. Sits between tool_interceptor (records taint after
tool execution) and tool_approval (checks taint before tool execution).
Prevents the classic prompt-injection → command-injection attack chain
by escalating suspicious tool calls to user approval.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from enum import StrEnum, unique

logger = logging.getLogger(__name__)


@unique
class TaintLabel(StrEnum):
    """Categories of tainted data flowing through the session."""

    EXTERNAL_NETWORK = "external_network"
    SECRET = "secret"
    PII_SENSITIVE = "pii_sensitive"


TAINT_SINK_POLICIES: dict[str, frozenset[TaintLabel]] = {
    "bash_code_execute_tool": frozenset({TaintLabel.EXTERNAL_NETWORK}),
    "shell_exec": frozenset({TaintLabel.EXTERNAL_NETWORK}),
    "file_write_tool": frozenset({TaintLabel.EXTERNAL_NETWORK}),
    "file_edit_tool": frozenset({TaintLabel.EXTERNAL_NETWORK}),
    "web_fetch_tool": frozenset({TaintLabel.SECRET}),
    "browser_navigate_tool": frozenset({TaintLabel.SECRET}),
    "browser_snapshot_tool": frozenset({TaintLabel.SECRET}),
    "browser_extract_tool": frozenset({TaintLabel.SECRET}),
}

_BASH_EGRESS_RE = re.compile(
    r"(?:\bcurl\b|\bwget\b|\bnc\b|\bncat\b|\bsocat\b|\bssh\b|\bscp\b|\brsync\b|\bftp\b)[\s\S]{1,60}https?://|"
    r"(?:\bcurl\b|\bwget\b|\bnc\b|\bncat\b|\bsocat\b)\s+-[A-Za-z0-9]*[dF]",
    re.IGNORECASE,
)


class TaintTracker:
    """Accumulates taint labels and their sources for the current Agent session.

    Once a label is added, it persists for the entire session.
    This is conservative by design — we cannot know whether the LLM
    has "forgotten" the tainted data from its context.
    """

    __slots__ = ("_allowed_sinks", "_taints")

    def __init__(self) -> None:
        # Maps TaintLabel to a set of sources (e.g., URLs, file paths)
        self._taints: dict[TaintLabel, set[str]] = {}
        # Session-approved sink identifiers or domain hostnames
        self._allowed_sinks: set[str] = set()

    def allow_session_sink(self, identifier: str) -> None:
        """Allow a specific sink tool name or destination hostname for this session."""
        if identifier:
            self._allowed_sinks.add(identifier.strip().lower())

    def record(self, label: TaintLabel, source: str | None = None) -> None:
        """Record that tainted data of the given type is now in the LLM context.

        Args:
            label: The category of taint.
            source: Optional specific source of the taint (e.g., a URL).
        """
        if label not in self._taints:
            self._taints[label] = set()
            logger.warning("[TAINT] Recorded new label: %s", label)

        if source and source not in self._taints[label]:
            self._taints[label].add(source)
            logger.info("[TAINT] Added source '%s' to label %s", source, label)

    def record_tool_output(self, tool_name: str, tool_input: dict[str, object] | None = None) -> None:
        """Record taint from a tool's output, extracting source via safety metadata."""
        from myrm_agent_harness.agent.security.tool_registry import resolve_safety_metadata

        meta = resolve_safety_metadata(tool_name)
        if not meta.taint_label:
            return

        try:
            label = TaintLabel(meta.taint_label)
        except ValueError:
            logger.warning("[TAINT] Invalid taint label '%s' for tool %s", meta.taint_label, tool_name)
            return

        source = None
        extractor_failed = False
        if tool_input and meta.taint_extractor:
            if callable(meta.taint_extractor):
                try:
                    source = meta.taint_extractor(tool_input)
                except Exception as e:
                    logger.warning("[TAINT] Extractor failed for %s: %s", tool_name, e)
                    extractor_failed = True
            elif isinstance(meta.taint_extractor, str):
                val = tool_input.get(meta.taint_extractor)
                if val:
                    source = str(val)

        # For conditional taint tools (e.g. file_read_tool only taints on secret files):
        if label == TaintLabel.SECRET and meta.taint_extractor and source is None and not extractor_failed:
            return

        self.record(label, source if source else None)

    def check_sink(
        self,
        tool_name: str,
        tool_input: dict[str, object] | None = None,
        trusted_hosts: set[str] | frozenset[str] | None = None,
    ) -> dict[TaintLabel, set[str]] | None:
        """Check if calling this tool violates any taint policy.

        Returns a dictionary mapping conflicting TaintLabels to their sources,
        or None if clean or whitelisted.
        """
        tool_key = tool_name.lower().strip()
        if tool_key in self._allowed_sinks:
            return None

        if tool_input:
            url_str = tool_input.get("url")
            if isinstance(url_str, str):
                try:
                    from urllib.parse import urlparse

                    host = urlparse(url_str).netloc.lower()
                    if host:
                        if host in self._allowed_sinks:
                            return None
                        if trusted_hosts and (
                            host in trusted_hosts
                            or any(host.endswith(f".{th.lower()}") for th in trusted_hosts)
                        ):
                            return None
                except Exception:
                    pass

        blocked = set(TAINT_SINK_POLICIES.get(tool_name, frozenset()))

        # Dynamic sink escalation: if session holds SECRET taint and bash attempts network transfer
        if (
            tool_name in ("bash_code_execute_tool", "shell_exec")
            and TaintLabel.SECRET in self._taints
            and tool_input
        ):
            cmd_str = str(tool_input.get("command") or tool_input.get("cmd") or "")
            if _BASH_EGRESS_RE.search(cmd_str):
                blocked.add(TaintLabel.SECRET)

        if not blocked:
            return None

        conflict_labels = set(self._taints.keys()) & blocked
        if not conflict_labels:
            return None

        return {label: self._taints[label] for label in conflict_labels}

    @property
    def labels(self) -> frozenset[TaintLabel]:
        return frozenset(self._taints.keys())

    @property
    def is_tainted(self) -> bool:
        return bool(self._taints)


_taint_tracker_var: ContextVar[TaintTracker] = ContextVar("taint_tracker")


def get_taint_tracker() -> TaintTracker:
    """Get the TaintTracker for the current async context.

    Creates a new one if none exists (lazy initialization).
    """
    try:
        return _taint_tracker_var.get()
    except LookupError:
        tracker = TaintTracker()
        _taint_tracker_var.set(tracker)
        return tracker


def reset_taint_tracker() -> None:
    """Reset taint state. Call at the start of each Agent run."""
    _taint_tracker_var.set(TaintTracker())
