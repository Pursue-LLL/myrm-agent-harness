"""Desktop interaction capture driver: AX snapshots + incremental diff -> recorded events.

[INPUT]
- myrm_agent_harness.toolkits.computer_use.dref.types::{ElementRef, SnapshotMeta, SnapshotScope}
- myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch::capture_snapshot
- myrm_agent_harness.toolkits.computer_use.perception.ax_diff::{RefDiff, compute_ref_diff}
- myrm_agent_harness.toolkits.computer_use.recording.types::DesktopRecordedEvent

[OUTPUT]
- DesktopCaptureDriver: class — poll foreground AX snapshots, diff consecutive frames, and
  emit DesktopRecordedEvent entries describing what the user did

[POS]
Harness framework layer. Converts the existing platform perception layer (AX/UIA/AT-SPI
snapshot + incremental diff) into an interaction event stream, so a recorder can build a
skill draft from a real demonstration instead of hand-entered placeholder steps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from myrm_agent_harness.toolkits.computer_use import safety
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    ElementRef,
    SnapshotMeta,
)
from myrm_agent_harness.toolkits.computer_use.perception.ax_diff import compute_ref_diff
from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import capture_snapshot
from myrm_agent_harness.toolkits.computer_use.perception.overlay_roles import (
    normalize_desktop_role,
)
from myrm_agent_harness.toolkits.computer_use.recording.types import (
    DesktopRecordedEvent,
    RecordedActionType,
)

# AX trees are noisy: container relayout churns many refs per user action. Emitting every
# changed ref would flood the event stream with non-actions, so a single poll collapses to at
# most this many events, ordered by change kind (navigation first, then text input).
_MAX_EVENTS_PER_POLL = 3

# Elements whose `value` changed are the observable trace of an interaction, and the emitted
# action depends on the role: text entry produces a `type` event carrying the new value, while
# a value change on any other interactive role (checkbox, radio, switch, slider, option, tab,
# combobox) is the result of a click and must not be dropped. Generic fallback roles are
# excluded so layout churn is not mistaken for an action.
_TEXT_ENTRY_OVERLAY_ROLES = frozenset({"textbox", "searchbox"})
_GENERIC_OVERLAY_ROLES = frozenset({"clickable", "focusable"})


@dataclass(frozen=True)
class CaptureFrame:
    """One poll result: what changed since the previous frame."""

    events: tuple[DesktopRecordedEvent, ...]
    meta: SnapshotMeta
    refs: dict[str, ElementRef]


def _resolve_backend(capture_source: object) -> object:
    """Accept a DesktopSession (preferred) or a bare platform backend.

    A session stores its backend behind ``_backend`` (the same attribute the session's own
    snapshot path reads), so the lookup walks that chain rather than assuming a single hop.
    """
    platform_backends = {"MacOSBackend", "WindowsBackend", "LinuxBackend"}
    candidate = capture_source
    for _ in range(3):
        if candidate.__class__.__name__ in platform_backends:
            return candidate
        nested = getattr(candidate, "_backend", None)
        if nested is None or nested is candidate:
            return candidate
        candidate = nested
    return candidate


class DesktopCaptureDriver:
    """Emit interaction events by diffing consecutive foreground AX snapshots.

    Usage::

        driver = DesktopCaptureDriver(desktop_session)
        frame = await driver.poll()   # first poll only primes the baseline
        ...
        frame = await driver.poll()   # subsequent polls yield events

    The first poll establishes a baseline and intentionally emits nothing: a diff needs a
    previous frame, and reporting every pre-existing element as "added" would fabricate
    interactions the user never performed.
    """

    def __init__(self, capture_source: object, *, app_scope: str = "all") -> None:
        self._backend = _resolve_backend(capture_source)
        self._app_scope = app_scope
        self._prev_refs: dict[str, ElementRef] = {}
        self._prev_meta: SnapshotMeta | None = None
        self._seq = 0

    @property
    def event_count(self) -> int:
        """Number of events emitted so far."""
        return self._seq

    def reset(self) -> None:
        """Drop the diff baseline so the next poll re-primes without emitting."""
        self._prev_refs = {}
        self._prev_meta = None
        self._seq = 0

    async def poll(self) -> CaptureFrame:
        """Capture the foreground AX tree and emit events for what changed since the last poll."""
        app_name = None if self._app_scope in ("", "all") else self._app_scope
        meta, refs = capture_snapshot(
            self._backend,
            "foreground",
            app_name=app_name,
        )

        # Permission-denied or empty captures would diff as "everything removed" and invent
        # interactions; skip them and keep the previous baseline intact.
        if meta.needs_permission or not refs:
            return CaptureFrame(events=(), meta=meta, refs=refs)

        # Same sensitive-app guard the semantic desktop path enforces: terminals, password
        # managers and the Myrm/Cursor host UI must never be captured into a skill. Re-baseline
        # instead of diffing, so returning to a safe app does not replay the blocked window's
        # elements as fresh interactions.
        if safety.is_sensitive_app(meta.app_name, meta.window_title, meta.app_id):
            self._prev_refs = refs
            self._prev_meta = meta
            return CaptureFrame(events=(), meta=meta, refs=refs)

        if not self._prev_refs or self._prev_meta is None:
            self._prev_refs = refs
            self._prev_meta = meta
            return CaptureFrame(events=(), meta=meta, refs=refs)

        diff = compute_ref_diff(self._prev_refs, refs, self._prev_meta, meta)
        events = tuple(self._events_from_diff(diff, meta))

        self._prev_refs = refs
        self._prev_meta = meta
        return CaptureFrame(events=events, meta=meta, refs=refs)

    def _events_from_diff(self, diff: object, meta: SnapshotMeta) -> list[DesktopRecordedEvent]:
        """Translate a ref diff into a bounded, ordered list of interaction events."""
        app_changed = self._prev_meta is not None and self._prev_meta.app_name != meta.app_name
        emitted: list[DesktopRecordedEvent] = []

        if app_changed:
            emitted.append(self._build_event(meta=meta, action=RecordedActionType.WINDOW_FOCUS.value))

        added = getattr(diff, "added", [])
        updated = getattr(diff, "updated", [])

        # Navigation/state changes: interactable roles that appeared.
        for element in added:
            if len(emitted) >= _MAX_EVENTS_PER_POLL:
                break
            emitted.append(
                self._build_event(meta=meta, action=RecordedActionType.CLICK.value, element=element)
            )

        # Text entry: value changed on an input-bearing role.
        for change in updated:
            if len(emitted) >= _MAX_EVENTS_PER_POLL:
                break
            element = getattr(change, "element", None)
            fields = getattr(change, "changed_fields", ())
            if element is None or "value" not in fields:
                continue
            overlay_role = normalize_desktop_role(element.role)
            if overlay_role in _TEXT_ENTRY_OVERLAY_ROLES:
                emitted.append(
                    self._build_event(meta=meta, action=RecordedActionType.TYPE.value, element=element)
                )
            elif overlay_role not in _GENERIC_OVERLAY_ROLES:
                # A value change on a checkbox/radio/switch/slider is the *result* of a click;
                # dropping it would lose the interaction from the recorded skill.
                emitted.append(
                    self._build_event(meta=meta, action=RecordedActionType.CLICK.value, element=element)
                )

        return emitted

    def _build_event(
        self,
        *,
        meta: SnapshotMeta,
        action: str,
        element: ElementRef | None = None,
    ) -> DesktopRecordedEvent:
        self._seq += 1
        return DesktopRecordedEvent(
            seq=self._seq,
            timestamp=time.time(),
            action=action,
            app_name=meta.app_name,
            bundle_id=meta.app_id or None,
            window_title=meta.window_title,
            # `ref_id` is a per-snapshot positional index (`d<N>` by tree order), so it is
            # meaningless to a later session. Emitting it would make the synthesizer mark the
            # step as a semantic @dref interaction whose target silently points elsewhere at
            # replay. Leaving it unset keeps steps on the re-resolve-by-element path, and the
            # role/title below carry the semantic identity that path needs.
            dref_id=None,
            element_role=element.role if element else None,
            element_title=element.name if element else None,
            # Password fields never surface their value into the event stream.
            value=(
                element.value
                if element and action == RecordedActionType.TYPE.value
                else None
            ),
        )
