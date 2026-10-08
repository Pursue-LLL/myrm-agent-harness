# [INPUT]: ChatHeadPointer, SchemaVersion, VersionGateResult
# [OUTPUT]: gate_chat_head_version
# [POS]: agent/context_management/chat_head_sync/chat_head_version_gate.py

"""Version gate for chat head reader admission checking.

[INPUT]
- ChatHeadPointer: Chat head pointer to check.
- SchemaVersion: Reader supported schema version.

[OUTPUT]
- gate_chat_head_version: Evaluation function admitting or refusing reader requests.

[POS]
Reader admission gate evaluating compatibility on head before fetching any shard data.
"""

from __future__ import annotations

from .chat_head_types import ChatHeadPointer, SchemaVersion, VersionGateResult


def gate_chat_head_version(
    head: ChatHeadPointer,
    reader_supports: SchemaVersion,
) -> VersionGateResult:
    """Decide whether a reader may assemble the chat described by a head.

    Evaluated on the lightweight head before any immutable shard is retrieved.
    This guarantees that unreadable publications cost zero shard bandwidth and
    are never half-materialized.

    Core Invariant:
    1. Major is the reject boundary:
       A same-major publication is admitted regardless of its minor version.
       This enables unknown-variant passthrough: older readers safely render known
       blocks and retain unrecognized fields without bouncing new minor bumps.
    2. minReaderVersion is the safety escape hatch:
       When a writer introduces semantically breaking changes (e.g. irrevocable
       permissions, judge notice rows) that older readers would dangerously
       misinterpret, the writer stamps min_reader_version. Older readers below
       this floor are strictly blocked.
    """
    if head.schema_version.major != reader_supports.major:
        return VersionGateResult(
            ok=False,
            reason="unsupported-major",
            message=(
                f"Chat head major {head.schema_version.major} is not readable by "
                f"a reader on major {reader_supports.major}"
            ),
        )

    minimum = head.min_reader_version
    if minimum is not None and reader_supports.is_below(minimum):
        return VersionGateResult(
            ok=False,
            reason="reader-below-minimum",
            message=(
                f"This chat requires a reader on {minimum.major}.{minimum.minor} or newer; "
                f"this reader is {reader_supports.major}.{reader_supports.minor}"
            ),
        )

    return VersionGateResult(ok=True)
