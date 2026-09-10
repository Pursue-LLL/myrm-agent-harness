"""Catalog Attribute Normalization and Graceful Filter Relaxation Suite.

[INPUT]
- typing::Literal, Sequence, Mapping
- pydantic::BaseModel, Field
- myrm_agent_harness.backends.commerce.types::Product, ProductFilter

[OUTPUT]
- MeasurementDimension: ("weight" | "length" | "volume")
- NormalizedMeasurement: Normalized measurement dataclass with SI canonical values
- parse_measurement: Robust parser across mixed unit strings (e.g. '500g', '1.2 lbs', '15 in')
- extract_attributes_from_text: Text-to-attribute distillation for unstructured catalog items
- RelaxationAdvice: Transparent explanation and nearest ladder threshold proposal
- GracefulFilterResult: Result envelope holding matched items and explicit relaxation advice
- filter_with_graceful_relaxation: Deterministic filter engine with smart relaxation fallback

[POS]
Addresses mixed catalog units and eliminates deceptive silent filter drops.
"""

from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, Field

from myrm_agent_harness.backends.commerce.types import Product, ProductFilter

MeasurementDimension = Literal["weight", "length", "volume"]

# Conversion ratios to canonical base units:
# weight -> gram (g)
# length -> centimeter (cm)
# volume -> milliliter (ml)
WEIGHT_RATIOS: dict[str, float] = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
    "pound": 453.592,
    "pounds": 453.592,
}

LENGTH_RATIOS: dict[str, float] = {
    "mm": 0.1,
    "millimeter": 0.1,
    "cm": 1.0,
    "centimeter": 1.0,
    "centimeters": 1.0,
    "m": 100.0,
    "meter": 100.0,
    "meters": 100.0,
    "in": 2.54,
    "inch": 2.54,
    "inches": 2.54,
    "ft": 30.48,
    "foot": 30.48,
    "feet": 30.48,
}

VOLUME_RATIOS: dict[str, float] = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "fl_oz": 29.5735,
    "floz": 29.5735,
}

_NUM_UNIT_PATTERN = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z_]+)\s*$",
    re.IGNORECASE,
)


class NormalizedMeasurement(BaseModel):
    """Canonical SI unit normalized representation of a physical measurement."""

    raw_value: str
    dimension: MeasurementDimension
    numeric_value: float
    original_unit: str
    canonical_unit: str
    canonical_value: float


def parse_measurement(
    raw: str | float,
    dimension_hint: MeasurementDimension | None = None,
) -> NormalizedMeasurement | None:
    """Parse a mixed unit string into canonical base metric (g, cm, ml)."""
    if isinstance(raw, (int, float)):
        # Default float with dimension hint
        dim = dimension_hint or "weight"
        base_unit = "g" if dim == "weight" else ("cm" if dim == "length" else "ml")
        return NormalizedMeasurement(
            raw_value=str(raw),
            dimension=dim,
            numeric_value=float(raw),
            original_unit=base_unit,
            canonical_unit=base_unit,
            canonical_value=float(raw),
        )

    match = _NUM_UNIT_PATTERN.match(raw.strip())
    if not match:
        return None

    val_str, unit_str = match.groups()
    val = float(val_str)
    unit_lower = unit_str.lower()

    if unit_lower in WEIGHT_RATIOS:
        ratio = WEIGHT_RATIOS[unit_lower]
        return NormalizedMeasurement(
            raw_value=raw,
            dimension="weight",
            numeric_value=val,
            original_unit=unit_lower,
            canonical_unit="g",
            canonical_value=round(val * ratio, 4),
        )
    elif unit_lower in LENGTH_RATIOS:
        ratio = LENGTH_RATIOS[unit_lower]
        return NormalizedMeasurement(
            raw_value=raw,
            dimension="length",
            numeric_value=val,
            original_unit=unit_lower,
            canonical_unit="cm",
            canonical_value=round(val * ratio, 4),
        )
    elif unit_lower in VOLUME_RATIOS:
        ratio = VOLUME_RATIOS[unit_lower]
        return NormalizedMeasurement(
            raw_value=raw,
            dimension="volume",
            numeric_value=val,
            original_unit=unit_lower,
            canonical_unit="ml",
            canonical_value=round(val * ratio, 4),
        )

    return None


FEATURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "waterproof": ("waterproof", "water-resistant", "water repellent", "防水"),
    "wireless": ("wireless", "bluetooth", "cordless", "无线", "蓝牙"),
    "noise_cancelling": ("noise cancelling", "noise-cancelling", "anc", "降噪"),
    "rechargeable": ("rechargeable", "battery", "usb-c charging", "充电"),
    "organic": ("organic", "natural", "eco-friendly", "有机", "环保"),
    "carbon_plate": ("carbon plate", "carbon fiber", "碳板"),
}


def extract_attributes_from_text(
    text: str,
    tags: tuple[str, ...] = (),
) -> dict[str, str | bool | float]:
    """Distill structured attributes and boolean flags from unstructured catalog description."""
    attributes: dict[str, str | bool | float] = {}
    combined_text = f"{text} {' '.join(tags)}".lower()

    # 1. Feature flags
    for feat_name, kws in FEATURE_KEYWORDS.items():
        if any(kw in combined_text for kw in kws):
            attributes[feat_name] = True

    # 2. Extract embedded physical measurements
    for word in re.findall(r"\b[0-9]+(?:\.[0-9]+)?\s*[a-zA-Z_]+\b", text):
        m = parse_measurement(word)
        if m:
            attributes[f"{m.dimension}_{m.canonical_unit}"] = m.canonical_value

    return attributes


class RelaxationAdvice(BaseModel):
    """Transparent advice explaining why zero results matched and what was relaxed."""

    bottleneck_dimension: str
    original_constraint: str
    suggested_threshold: str
    explanation: str
    relaxed_filter: ProductFilter


class GracefulFilterResult(BaseModel):
    """Filter result envelope supporting explicit relaxation rather than silent dropping."""

    matched_products: list[Product]
    total_count: int
    is_relaxed: bool = False
    relaxation_advice: RelaxationAdvice | None = None


def filter_with_graceful_relaxation(
    products: Sequence[Product],
    filters: ProductFilter,
) -> GracefulFilterResult:
    """Filter products deterministically with transparent graceful relaxation on zero matches.

    Unlike naive engines that secretly drop all filters when empty, this engine
    diagnoses the exact constraint bottleneck and returns compliant nearest recommendations.
    """
    # 1. Exact Filtering
    exact_matches = _apply_filter(products, filters)
    if exact_matches:
        return GracefulFilterResult(
            matched_products=exact_matches,
            total_count=len(exact_matches),
            is_relaxed=False,
            relaxation_advice=None,
        )

    # 2. Zero Matches: Perform Bottleneck Diagnosis and Nearest Relaxation
    # Case A: max_price bottleneck
    if filters.max_price is not None:
        relaxed_filter = ProductFilter(
            category=filters.category,
            min_price=filters.min_price,
            max_price=None,
            in_stock_only=filters.in_stock_only,
            tags=filters.tags,
        )
        relaxed_matches = _apply_filter(products, relaxed_filter)
        if relaxed_matches:
            # Find nearest available price
            lowest_available = min(p.base_price for p in relaxed_matches)
            advice = RelaxationAdvice(
                bottleneck_dimension="max_price",
                original_constraint=f"max_price <= {filters.max_price}",
                suggested_threshold=f"{lowest_available:.2f}",
                explanation=(
                    f"No products found under budget of ${filters.max_price:.2f}. "
                    f"Nearest matching item starts at ${lowest_available:.2f}."
                ),
                relaxed_filter=ProductFilter(
                    category=filters.category,
                    min_price=filters.min_price,
                    max_price=lowest_available,
                    in_stock_only=filters.in_stock_only,
                    tags=filters.tags,
                ),
            )
            # Sort by price ascending
            sorted_matches = sorted(relaxed_matches, key=lambda p: p.base_price)
            return GracefulFilterResult(
                matched_products=sorted_matches,
                total_count=len(sorted_matches),
                is_relaxed=True,
                relaxation_advice=advice,
            )

    # Case B: in_stock bottleneck (only out of stock available)
    if filters.in_stock_only is True:
        relaxed_filter = ProductFilter(
            category=filters.category,
            min_price=filters.min_price,
            max_price=filters.max_price,
            in_stock_only=False,
            tags=filters.tags,
        )
        relaxed_matches = _apply_filter(products, relaxed_filter)
        if relaxed_matches:
            advice = RelaxationAdvice(
                bottleneck_dimension="in_stock_only",
                original_constraint="in_stock_only == True",
                suggested_threshold="include backorder / restock candidates",
                explanation="All exact matches are currently out of stock. Backorder items shown.",
                relaxed_filter=relaxed_filter,
            )
            return GracefulFilterResult(
                matched_products=relaxed_matches,
                total_count=len(relaxed_matches),
                is_relaxed=True,
                relaxation_advice=advice,
            )

    # Case C: category bottleneck (fall back to all categories if specified)
    if filters.category:
        relaxed_filter = ProductFilter(
            category=None,
            min_price=filters.min_price,
            max_price=filters.max_price,
            in_stock_only=filters.in_stock_only,
            tags=filters.tags,
        )
        relaxed_matches = _apply_filter(products, relaxed_filter)
        if relaxed_matches:
            advice = RelaxationAdvice(
                bottleneck_dimension="category",
                original_constraint=f"category == '{filters.category}'",
                suggested_threshold="all categories",
                explanation=f"No products in category '{filters.category}' matched your criteria.",
                relaxed_filter=relaxed_filter,
            )
            return GracefulFilterResult(
                matched_products=relaxed_matches,
                total_count=len(relaxed_matches),
                is_relaxed=True,
                relaxation_advice=advice,
            )

    # If still completely empty
    return GracefulFilterResult(
        matched_products=[],
        total_count=0,
        is_relaxed=False,
        relaxation_advice=None,
    )


def _apply_filter(products: Sequence[Product], filters: ProductFilter) -> list[Product]:
    """Helper to apply standard product filter constraints."""
    result: list[Product] = []
    for p in products:
        if filters.category and p.category.lower() != filters.category.lower():
            continue
        if filters.min_price is not None and p.base_price < filters.min_price:
            continue
        if filters.max_price is not None and p.base_price > filters.max_price:
            continue
        if filters.in_stock_only and not p.in_stock:
            continue
        if filters.tags:
            tag_set = {t.lower() for t in p.tags}
            if not all(req.lower() in tag_set for req in filters.tags):
                continue
        result.append(p)
    return result
