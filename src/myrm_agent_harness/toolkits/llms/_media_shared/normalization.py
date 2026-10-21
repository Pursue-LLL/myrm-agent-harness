"""Geometry and duration normalization engine for media generation.

[INPUT]

[OUTPUT]
- Resolved parameters snapped to closest supported values
- NormalizationRecord list for transparency

[POS]
Used by video/generator.py and future image/generator.py to normalize
user-requested geometry to provider-supported values before API calls.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .types import ModeCapabilities, NormalizationRecord, SizeSpec

_ASPECT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$")
_SIZE_RE = re.compile(r"^(\d+)\s*[xX×]\s*(\d+)$")


@dataclass(frozen=True, slots=True)
class _ParsedRatio:
    w: float
    h: float
    value: float


@dataclass(frozen=True, slots=True)
class _ParsedSize:
    w: int
    h: int
    ratio: float
    area: int


def _parse_ratio(raw: str | None) -> _ParsedRatio | None:
    if not raw:
        return None
    m = _ASPECT_RE.match(raw.strip())
    if not m:
        return None
    w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0:
        return None
    return _ParsedRatio(w=w, h=h, value=w / h)


def _parse_size(raw: str | None) -> _ParsedSize | None:
    if not raw:
        return None
    m = _SIZE_RE.match(raw.strip())
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        return None
    return _ParsedSize(w=w, h=h, ratio=w / h, area=w * h)


def _gcd(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a or 1


def derive_ratio_from_size(size: str) -> str | None:
    """Derive 'W:H' aspect-ratio string from a 'WxH' size string."""
    p = _parse_size(size)
    if not p:
        return None
    d = _gcd(p.w, p.h)
    return f"{p.w // d}:{p.h // d}"


def resolve_closest_ratio(
    *,
    requested_ratio: str | None = None,
    requested_size: str | None = None,
    supported_ratios: tuple[str, ...],
) -> str | None:
    """Find the closest supported aspect ratio to the requested one.

    Uses log-ratio distance for perceptual closeness, with cross-product
    as tiebreaker for exact integer ratios.
    """
    if not supported_ratios:
        return requested_ratio or (derive_ratio_from_size(requested_size) if requested_size else None)

    if requested_ratio and requested_ratio in supported_ratios:
        return requested_ratio

    target = _parse_ratio(requested_ratio) or (
        _parse_ratio(derive_ratio_from_size(requested_size)) if requested_size else None
    )
    if not target:
        return None

    best_val: str | None = None
    best_score: tuple[float, float] | None = None
    for candidate in supported_ratios:
        parsed = _parse_ratio(candidate)
        if not parsed:
            continue
        primary = abs(math.log(parsed.value / target.value)) if target.value > 0 else float("inf")
        secondary = abs(parsed.w * target.h - target.w * parsed.h)
        score = (primary, secondary)
        if best_score is None or score < best_score:
            best_val = candidate
            best_score = score

    return best_val


def resolve_closest_size(
    *,
    requested_size: str | None = None,
    requested_ratio: str | None = None,
    supported_sizes: tuple[SizeSpec, ...],
) -> SizeSpec | None:
    """Find the closest supported size by aspect-ratio then area distance."""
    if not supported_sizes:
        return None

    req = _parse_size(requested_size)
    req_ratio = _parse_ratio(requested_ratio)

    if not req and not req_ratio:
        return None

    target_ratio = req.ratio if req else (req_ratio.value if req_ratio else 1.0)
    target_area = req.area if req else 0

    best: SizeSpec | None = None
    best_score: tuple[float, float] | None = None
    for s in supported_sizes:
        ratio = s.aspect_ratio
        primary = abs(math.log(ratio / target_ratio)) if target_ratio > 0 else float("inf")
        area = s.width * s.height
        secondary = abs(math.log(area / target_area)) if target_area > 0 else float(area)
        score = (primary, secondary)
        if best_score is None or score < best_score:
            best = s
            best_score = score

    return best


def resolve_closest_duration(
    *,
    requested: int | None,
    supported_durations: tuple[int, ...],
    max_duration: int | None = None,
) -> int | None:
    """Snap requested duration to closest supported value, respecting max."""
    if requested is None:
        return None

    clamped = max(1, round(requested))

    if max_duration is not None and max_duration > 0:
        clamped = min(clamped, max_duration)

    if not supported_durations:
        return clamped

    return min(supported_durations, key=lambda d: (abs(d - clamped), -d))


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Collected result of normalizing geometry + duration against capabilities."""

    aspect_ratio: str | None = None
    size: SizeSpec | None = None
    duration_seconds: int | None = None
    records: tuple[NormalizationRecord, ...] | None = None


def normalize_params(
    *,
    caps: ModeCapabilities,
    requested_ratio: str | None = None,
    requested_size: str | None = None,
    requested_duration: int | None = None,
) -> NormalizationResult:
    """Normalize requested geometry + duration against mode capabilities.

    Returns resolved values and NormalizationRecord list for any adjustments.
    """
    records: list[NormalizationRecord] = []
    ratio = requested_ratio
    size: SizeSpec | None = None
    duration = requested_duration

    if caps.supported_aspect_ratios:
        resolved = resolve_closest_ratio(
            requested_ratio=requested_ratio,
            requested_size=requested_size,
            supported_ratios=caps.supported_aspect_ratios,
        )
        if resolved and resolved != requested_ratio:
            records.append(
                NormalizationRecord(
                    field="aspect_ratio",
                    requested=requested_ratio or (requested_size or ""),
                    applied=resolved,
                    reason="snapped to closest supported ratio",
                )
            )
        ratio = resolved

    if caps.supported_sizes:
        resolved_size = resolve_closest_size(
            requested_size=requested_size,
            requested_ratio=ratio,
            supported_sizes=caps.supported_sizes,
        )
        if resolved_size:
            req_parsed = _parse_size(requested_size)
            if req_parsed and (req_parsed.w != resolved_size.width or req_parsed.h != resolved_size.height):
                records.append(
                    NormalizationRecord(
                        field="size",
                        requested=requested_size or "",
                        applied=f"{resolved_size.width}x{resolved_size.height}",
                        reason="snapped to closest supported size",
                    )
                )
            size = resolved_size

    if caps.supported_durations or caps.max_duration_seconds:
        resolved_dur = resolve_closest_duration(
            requested=requested_duration,
            supported_durations=caps.supported_durations,
            max_duration=caps.max_duration_seconds,
        )
        if resolved_dur is not None and resolved_dur != requested_duration:
            records.append(
                NormalizationRecord(
                    field="duration_seconds",
                    requested=str(requested_duration),
                    applied=str(resolved_dur),
                    reason="snapped to closest supported duration",
                )
            )
        duration = resolved_dur

    return NormalizationResult(
        aspect_ratio=ratio,
        size=size,
        duration_seconds=duration,
        records=tuple(records) if records else None,
    )
