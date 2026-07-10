"""Unit tests for desktop SOM overlay."""

from __future__ import annotations

import base64
import io

from PIL import Image

from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import refs_for_view_update
from myrm_agent_harness.toolkits.computer_use.perception.renderer import render_snapshot_tree
from myrm_agent_harness.toolkits.computer_use.som_overlay import (
    MAX_SOM_OVERLAY_ELEMENTS,
    apply_som_overlay_to_jpeg_base64,
    build_som_index_map,
)


def _make_jpeg_base64(width: int, height: int, color: tuple[int, int, int] = (240, 240, 240)) -> str:
    image = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def test_build_som_index_map_stable_sorted_interactive_only() -> None:
    refs = {
        "d2": ElementRef(ref_id="d2", role="AXStaticText", name="Label", bbox=BBox(0, 0, 50, 20), backend_key="k2"),
        "d1": ElementRef(ref_id="d1", role="AXButton", name="OK", bbox=BBox(10, 10, 40, 30), backend_key="k1"),
        "d3": ElementRef(ref_id="d3", role="AXTextField", name="Input", bbox=BBox(20, 20, 80, 24), backend_key="k3"),
    }

    index_map = build_som_index_map(refs)

    assert index_map == {"d1": 1, "d3": 2}
    assert "d2" not in index_map


def test_build_som_index_map_respects_max_elements() -> None:
    refs = {
        f"d{i}": ElementRef(
            ref_id=f"d{i}",
            role="AXButton",
            name=f"B{i}",
            bbox=BBox(i, i, 10, 10),
            backend_key=f"k{i}",
        )
        for i in range(MAX_SOM_OVERLAY_ELEMENTS + 5)
    }

    index_map = build_som_index_map(refs)

    assert len(index_map) == MAX_SOM_OVERLAY_ELEMENTS
    assert index_map["d0"] == 1
    assert f"d{MAX_SOM_OVERLAY_ELEMENTS - 1}" in index_map
    assert f"d{MAX_SOM_OVERLAY_ELEMENTS}" not in index_map


def test_apply_som_overlay_returns_modified_jpeg() -> None:
    refs = {
        "d1": ElementRef(ref_id="d1", role="AXButton", name="OK", bbox=BBox(100, 100, 80, 40), backend_key="k1"),
    }
    scaler = CoordinateScaler(
        screen_width=800,
        screen_height=600,
        sent_width=400,
        sent_height=300,
        dpi_scale=1.0,
    )
    original_b64 = _make_jpeg_base64(400, 300)
    index_map = {"d1": 1}

    overlaid_b64 = apply_som_overlay_to_jpeg_base64(original_b64, refs, scaler, index_map)

    assert overlaid_b64 != original_b64
    raw = base64.standard_b64decode(overlaid_b64)
    image = Image.open(io.BytesIO(raw))
    assert image.size == (400, 300)


def test_render_snapshot_tree_adds_som_prefix() -> None:
    meta = SnapshotMeta(
        ref_count=2,
        app_name="App",
        window_title="Window",
        scope="foreground",
    )
    refs = {
        "d1": ElementRef(ref_id="d1", role="AXButton", name="OK", bbox=BBox(0, 0, 10, 10), backend_key="k1"),
        "d2": ElementRef(ref_id="d2", role="AXStaticText", name="Hi", bbox=BBox(1, 1, 5, 5), backend_key="k2"),
    }
    som_index_map = {"d1": 1}

    body, enriched = render_snapshot_tree(meta, refs, som_index_map=som_index_map)

    assert "[1] @d1" in body
    assert "@d2" in body
    assert "[N] labels match numbered regions" in body
    assert enriched.ref_count == 2


def test_refs_for_view_update_fills_nth_from_som_map() -> None:
    refs = {
        "d1": ElementRef(ref_id="d1", role="AXButton", name="OK", bbox=BBox(0, 0, 10, 10), backend_key="k1"),
    }
    payload = refs_for_view_update(refs, viewport_width=800, viewport_height=600, som_index_map={"d1": 3})
    assert payload["d1"]["nth"] == 3
