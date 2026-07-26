"""Tests for perception/ax_diff.py — incremental AX tree diff."""

from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.perception.ax_diff import (
    RefDiff,
    compute_ref_diff,
)
from myrm_agent_harness.toolkits.computer_use.perception.renderer import (
    render_diff_tree,
    render_snapshot_tree,
)


def _make_meta(app: str = "WPS", scope: str = "window_title") -> SnapshotMeta:
    return SnapshotMeta(ref_count=0, app_name=app, window_title="Sheet1", scope=scope)


def _make_ref(ref_id: str, role: str, name: str, value: str = "", x: int = 0, y: int = 0) -> ElementRef:
    return ElementRef(
        ref_id=ref_id,
        role=role,
        name=name,
        bbox=BBox(x=x, y=y, width=100, height=30),
        backend_key=f"key_{ref_id}",
        actions=("click", "fill"),
        value=value,
    )


class TestComputeRefDiff:
    """Test compute_ref_diff correctness."""

    def test_first_snapshot_full_view(self) -> None:
        curr = {"d1": _make_ref("d1", "AXTextField", "Name")}
        diff = compute_ref_diff({}, curr, None, _make_meta())
        assert diff.use_full_view is True
        assert diff.full_view_reason == "first_snapshot"

    def test_app_change_full_view(self) -> None:
        prev = {"d1": _make_ref("d1", "AXTextField", "Name")}
        curr = {"d1": _make_ref("d1", "AXTextField", "Name")}
        diff = compute_ref_diff(prev, curr, _make_meta("TextEdit"), _make_meta("WPS"))
        assert diff.use_full_view is True
        assert diff.full_view_reason == "app_changed"

    def test_no_change_zero_diff(self) -> None:
        meta = _make_meta()
        refs = {
            "d1": _make_ref("d1", "AXTextField", "Name", value="Alice", x=10, y=20),
            "d2": _make_ref("d2", "AXButton", "Submit", x=10, y=60),
        }
        diff = compute_ref_diff(refs, refs, meta, meta)
        assert diff.use_full_view is False
        assert len(diff.added) == 0
        assert len(diff.updated) == 0
        assert len(diff.removed) == 0

    def test_single_value_change(self) -> None:
        meta = _make_meta()
        prev = {
            "d1": _make_ref("d1", "AXTextField", "Name", value="", x=10, y=20),
            "d2": _make_ref("d2", "AXButton", "Submit", x=10, y=60),
        }
        curr = {
            "d1": _make_ref("d1", "AXTextField", "Name", value="Alice", x=10, y=20),
            "d2": _make_ref("d2", "AXButton", "Submit", x=10, y=60),
        }
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is False
        assert len(diff.added) == 0
        assert len(diff.updated) == 1
        assert diff.updated[0].ref_id == "d1"
        assert diff.updated[0].changed_fields == ("value",)
        assert len(diff.removed) == 0

    def test_added_and_removed(self) -> None:
        meta = _make_meta()
        stable = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"Stable{i}", x=i * 20) for i in range(5)}
        prev = {**stable, "d10": _make_ref("d10", "AXButton", "Cancel", x=200, y=60)}
        curr = {**stable, "d11": _make_ref("d11", "AXButton", "Confirm", x=200, y=100)}
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is False
        assert len(diff.added) == 1
        assert diff.added[0].ref_id == "d11"
        assert len(diff.removed) == 1
        assert "d10" in diff.removed

    def test_high_change_ratio_full_view(self) -> None:
        meta = _make_meta()
        prev = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"Btn{i}", x=i * 10) for i in range(10)}
        curr = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"New{i}", x=i * 10 + 200) for i in range(10)}
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is True
        assert "low_identity_confidence" in diff.full_view_reason or "high_change_ratio" in diff.full_view_reason

    def test_bbox_change_ignored(self) -> None:
        meta = _make_meta()
        prev = {"d1": _make_ref("d1", "AXTextField", "Name", x=10, y=20)}
        curr = {"d1": _make_ref("d1", "AXTextField", "Name", x=50, y=60)}
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is False
        assert len(diff.updated) == 0

    def test_low_identity_confidence_full_view(self) -> None:
        meta = _make_meta()
        prev = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"A{i}", x=i * 10) for i in range(10)}
        curr = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"Z{i}", x=i * 10) for i in range(10)}
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is True
        assert "low_identity_confidence" in diff.full_view_reason

    def test_multiple_updated_fields(self) -> None:
        meta = _make_meta()
        stable = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"Btn{i}", x=i * 20) for i in range(5)}
        prev_el = ElementRef(
            ref_id="d10",
            role="AXTextField",
            name="Name",
            bbox=BBox(x=10, y=200, width=100, height=30),
            backend_key="key_d10",
            actions=("click", "fill"),
            value="A",
        )
        curr_el = ElementRef(
            ref_id="d10",
            role="AXTextField",
            name="Name",
            bbox=BBox(x=10, y=200, width=100, height=30),
            backend_key="key_d10",
            actions=("click", "fill", "clear"),
            value="Bob",
        )
        prev = {**stable, "d10": prev_el}
        curr = {**stable, "d10": curr_el}
        diff = compute_ref_diff(prev, curr, meta, meta)
        assert diff.use_full_view is False
        assert len(diff.updated) == 1
        changed = set(diff.updated[0].changed_fields)
        assert "value" in changed
        assert "actions" in changed


class TestRenderDiffTree:
    """Test render_diff_tree output format."""

    def test_zero_change_message(self) -> None:
        meta = _make_meta()
        diff = RefDiff()
        text, enriched = render_diff_tree(meta, diff)
        assert "unchanged" in text
        assert "0 changes" in text
        assert enriched.token_estimate > 0

    def test_single_update_output(self) -> None:
        meta = _make_meta()
        from myrm_agent_harness.toolkits.computer_use.perception.ax_diff import UpdatedRef

        diff = RefDiff(
            updated=[
                UpdatedRef(
                    ref_id="d1",
                    element=_make_ref("d1", "AXTextField", "Name", value="Alice"),
                    changed_fields=("value",),
                )
            ]
        )
        text, enriched = render_diff_tree(meta, diff)
        assert "1 change" in text
        assert "~ @d1" in text
        assert "value" in text
        assert enriched.token_estimate > 0

    def test_diff_much_smaller_than_full(self) -> None:
        meta = SnapshotMeta(ref_count=80, app_name="WPS", window_title="Sheet1", scope="window_title")
        refs = {f"d{i}": _make_ref(f"d{i}", "AXButton", f"Button{i}", x=i * 10) for i in range(80)}

        full_text, _ = render_snapshot_tree(meta, refs)

        from myrm_agent_harness.toolkits.computer_use.perception.ax_diff import UpdatedRef

        diff = RefDiff(
            updated=[
                UpdatedRef(
                    ref_id="d0",
                    element=_make_ref("d0", "AXButton", "Button0", value="clicked"),
                    changed_fields=("value",),
                )
            ]
        )
        diff_text, _ = render_diff_tree(meta, diff)

        assert len(diff_text) < len(full_text) * 0.2

    def test_added_removed_format(self) -> None:
        meta = _make_meta()
        diff = RefDiff(
            added=[_make_ref("d5", "AXButton", "New")],
            removed=["d3"],
        )
        text, _ = render_diff_tree(meta, diff)
        assert "+ @d5" in text
        assert "- @d3" in text
        assert "(removed)" in text


class TestRegistryPreviousRefs:
    """Test DRefRegistry preserves previous snapshot."""

    def test_replace_stores_previous(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.dref.registry import DRefRegistry

        reg = DRefRegistry()
        meta1 = _make_meta("App1")
        refs1 = {"d1": _make_ref("d1", "AXButton", "Btn1")}
        reg.replace(refs1, meta1)

        assert reg.previous_refs == {}
        assert reg.previous_meta is None

        meta2 = _make_meta("App2")
        refs2 = {"d2": _make_ref("d2", "AXButton", "Btn2")}
        reg.replace(refs2, meta2)

        assert "d1" in reg.previous_refs
        assert reg.previous_meta is not None
        assert reg.previous_meta.app_name == "App1"
        assert reg.meta is not None
        assert reg.meta.app_name == "App2"
