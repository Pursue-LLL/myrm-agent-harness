"""Incremental AX tree diff for follow-up snapshots.

[INPUT]
- dref.types::{ElementRef, SnapshotMeta} (POS: @dref snapshot entries and metadata)

[OUTPUT]
- RefDiff: diff result with added/updated/removed entries
- compute_ref_diff(): compare two snapshots and produce a minimal diff

[POS]
Source-level token reduction for consecutive desktop snapshots.
Reduces follow-up AX tree output by 80%+ in continuous-interact scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta

_CHANGE_RATIO_FULL_VIEW_THRESHOLD = 0.6
_IDENTITY_CONFIDENCE_THRESHOLD = 0.3
_BBOX_PROXIMITY_PX = 120

_COMPARED_FIELDS = ("role", "name", "value", "actions")


@dataclass(frozen=True)
class UpdatedRef:
    """A ref that changed between two snapshots."""

    ref_id: str
    element: ElementRef
    changed_fields: tuple[str, ...]


@dataclass
class RefDiff:
    """Result of comparing two AX tree snapshots."""

    added: list[ElementRef] = field(default_factory=list)
    updated: list[UpdatedRef] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    use_full_view: bool = False
    full_view_reason: str = ""


def _identity_key(el: ElementRef) -> tuple[str, str]:
    return (el.role, el.name)


def _bbox_close(a: ElementRef, b: ElementRef) -> bool:
    dx = abs(a.bbox.center_x - b.bbox.center_x)
    dy = abs(a.bbox.center_y - b.bbox.center_y)
    return dx <= _BBOX_PROXIMITY_PX and dy <= _BBOX_PROXIMITY_PX


def _match_prev_to_curr(
    prev_refs: dict[str, ElementRef],
    curr_refs: dict[str, ElementRef],
) -> dict[str, str]:
    """Build prev_ref_id → curr_ref_id mapping using (role, name) + bbox proximity."""
    curr_by_key: dict[tuple[str, str], list[str]] = {}
    for ref_id, el in curr_refs.items():
        curr_by_key.setdefault(_identity_key(el), []).append(ref_id)

    mapping: dict[str, str] = {}
    used_curr: set[str] = set()

    for prev_id, prev_el in prev_refs.items():
        key = _identity_key(prev_el)
        candidates = curr_by_key.get(key, [])
        best_id: str | None = None
        best_dist = float("inf")
        for cid in candidates:
            if cid in used_curr:
                continue
            cel = curr_refs[cid]
            if _bbox_close(prev_el, cel):
                dist = abs(prev_el.bbox.center_x - cel.bbox.center_x) + abs(prev_el.bbox.center_y - cel.bbox.center_y)
                if dist < best_dist:
                    best_dist = dist
                    best_id = cid
        if best_id is not None:
            mapping[prev_id] = best_id
            used_curr.add(best_id)

    return mapping


def _changed_fields(prev: ElementRef, curr: ElementRef) -> tuple[str, ...]:
    changes: list[str] = []
    for f in _COMPARED_FIELDS:
        if getattr(prev, f) != getattr(curr, f):
            changes.append(f)
    return tuple(changes)


def compute_ref_diff(
    prev_refs: dict[str, ElementRef],
    curr_refs: dict[str, ElementRef],
    prev_meta: SnapshotMeta | None,
    curr_meta: SnapshotMeta,
) -> RefDiff:
    """Compare two AX tree snapshots and produce a minimal diff.

    Returns RefDiff with use_full_view=True when diff is unreliable
    (first snapshot, app change, high change ratio, low identity confidence).
    """
    if prev_meta is None or not prev_refs:
        return RefDiff(use_full_view=True, full_view_reason="first_snapshot")

    if prev_meta.app_name != curr_meta.app_name:
        return RefDiff(use_full_view=True, full_view_reason="app_changed")

    mapping = _match_prev_to_curr(prev_refs, curr_refs)

    matched_count = len(mapping)
    total = max(len(prev_refs), len(curr_refs), 1)
    identity_confidence = matched_count / total

    if identity_confidence < _IDENTITY_CONFIDENCE_THRESHOLD:
        return RefDiff(
            use_full_view=True,
            full_view_reason=f"low_identity_confidence({identity_confidence:.2f})",
        )

    mapped_curr_ids = set(mapping.values())

    diff = RefDiff()

    for curr_id, curr_el in curr_refs.items():
        if curr_id not in mapped_curr_ids:
            diff.added.append(curr_el)

    for prev_id, curr_id in mapping.items():
        prev_el = prev_refs[prev_id]
        curr_el = curr_refs[curr_id]
        fields = _changed_fields(prev_el, curr_el)
        if fields:
            diff.updated.append(
                UpdatedRef(
                    ref_id=curr_id,
                    element=curr_el,
                    changed_fields=fields,
                )
            )

    mapped_prev_ids = set(mapping.keys())
    for prev_id in prev_refs:
        if prev_id not in mapped_prev_ids:
            diff.removed.append(prev_id)

    change_count = len(diff.added) + len(diff.updated) + len(diff.removed)
    if total > 0 and change_count / total > _CHANGE_RATIO_FULL_VIEW_THRESHOLD:
        return RefDiff(
            use_full_view=True,
            full_view_reason=f"high_change_ratio({change_count}/{total})",
        )

    return diff
