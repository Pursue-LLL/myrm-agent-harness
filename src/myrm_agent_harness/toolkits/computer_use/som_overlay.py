"""Set-of-Mark (SOM) overlay for desktop screenshots.

Draws numbered labels on a JPEG screenshot so vision models can align image
regions with @dref entries in the companion text tree. Uses the same
coordinate scaling as vision actions (CoordinateScaler.screen_to_api).

[INPUT]
- coordinate_scaler::CoordinateScaler (POS: screen ↔ sent-image coordinate map)
- dref.types::ElementRef, BBox (POS: @dref element metadata)
- perception.macos_ax::normalize_desktop_role (POS: AX role → overlay role)
- PIL.Image (POS: image draw primitives)

[OUTPUT]
- build_som_index_map(): stable [N] → @dref assignment for interactive elements
- apply_som_overlay_to_jpeg_base64(): return JPEG base64 with [N] badges drawn

[POS]
Optional SOM annotation for multimodal desktop_snapshot (`include_screenshot=True`) and Desktop Inspector screenshot refresh.
"""

from __future__ import annotations

import base64
import io
import logging

from PIL import Image, ImageDraw, ImageFont

from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import normalize_desktop_role

logger = logging.getLogger(__name__)

MAX_SOM_OVERLAY_ELEMENTS = 80

_INTERACTIVE_OVERLAY_ROLES: frozenset[str] = frozenset(
    {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "menuitem",
        "tab",
        "switch",
        "slider",
        "spinbutton",
        "searchbox",
        "option",
        "listbox",
        "clickable",
        "focusable",
    }
)

_LABEL_FILL = (37, 99, 235, 220)
_LABEL_TEXT = (255, 255, 255, 255)
_BOX_OUTLINE = (37, 99, 235, 180)


def _is_interactive_element(element: ElementRef) -> bool:
    return normalize_desktop_role(element.role) in _INTERACTIVE_OVERLAY_ROLES


def build_som_index_map(
    refs: dict[str, ElementRef],
    *,
    max_elements: int = MAX_SOM_OVERLAY_ELEMENTS,
) -> dict[str, int]:
    """Assign stable 1-based indices to interactive @dref entries (sorted by ref_id)."""
    interactive_ids = sorted(ref_id for ref_id, element in refs.items() if _is_interactive_element(element))
    if max_elements > 0:
        interactive_ids = interactive_ids[:max_elements]
    return {ref_id: index for index, ref_id in enumerate(interactive_ids, start=1)}


def _bbox_to_image_rect(bbox: BBox, scaler: CoordinateScaler) -> tuple[int, int, int, int]:
    x1, y1 = scaler.screen_to_api(bbox.x, bbox.y)
    x2, y2 = scaler.screen_to_api(bbox.x + bbox.width, bbox.y + bbox.height)
    left = min(x1, x2)
    top = min(y1, y2)
    right = max(x1, x2)
    bottom = max(y1, y2)
    return left, top, right, bottom


def _load_font(size: int = 11) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def apply_som_overlay_to_jpeg_base64(
    jpeg_base64: str,
    refs: dict[str, ElementRef],
    scaler: CoordinateScaler,
    index_map: dict[str, int],
) -> str:
    """Draw [N] badges and light bounding boxes on a JPEG screenshot."""
    if not index_map:
        return jpeg_base64

    try:
        raw = base64.standard_b64decode(jpeg_base64)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except (OSError, ValueError) as exc:
        logger.warning("SOM overlay skipped: invalid JPEG (%s)", exc)
        return jpeg_base64

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _load_font()

    for ref_id, nth in index_map.items():
        element = refs.get(ref_id)
        if element is None:
            continue
        left, top, right, bottom = _bbox_to_image_rect(element.bbox, scaler)
        if right - left < 2 or bottom - top < 2:
            continue
        draw.rectangle((left, top, right, bottom), outline=_BOX_OUTLINE, width=2)
        label = str(nth)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        pad = 2
        badge_left = left
        badge_top = max(0, top - text_h - pad * 2)
        draw.rectangle(
            (badge_left, badge_top, badge_left + text_w + pad * 2, badge_top + text_h + pad * 2),
            fill=_LABEL_FILL,
        )
        draw.text((badge_left + pad, badge_top + pad), label, fill=_LABEL_TEXT, font=font)

    composed = Image.alpha_composite(image, overlay).convert("RGB")
    buf = io.BytesIO()
    composed.save(buf, format="JPEG", quality=75)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
