"""Unit tests for Catalog Attribute Normalization and Graceful Filter Relaxation.

[INPUT]
- myrm_agent_harness.backends.commerce::*

[OUTPUT]
- test_mixed_weight_normalization: g, kg, oz, lbs unit conversions
- test_mixed_length_volume_normalization: cm, inch, ml, fl_oz conversions
- test_text_to_attribute_distillation: Automatic feature extraction from unstructured copy
- test_graceful_filter_relaxation_exact_matches: Normal path without relaxation
- test_graceful_filter_relaxation_price_bottleneck: Explicit diagnostic on budget overflow

[POS]
Unit tests verifying Commerce Clarity catalog rigor requirements.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.commerce import (
    GracefulFilterResult,
    NormalizedMeasurement,
    Product,
    ProductFilter,
    RelaxationAdvice,
    extract_attributes_from_text,
    filter_with_graceful_relaxation,
    parse_measurement,
)


def test_mixed_weight_normalization() -> None:
    # 500 grams
    m_g = parse_measurement("500g")
    assert m_g is not None
    assert m_g.dimension == "weight"
    assert m_g.canonical_unit == "g"
    assert m_g.canonical_value == 500.0

    # 1.5 kg -> 1500 g
    m_kg = parse_measurement("1.5 kg")
    assert m_kg is not None
    assert m_kg.canonical_unit == "g"
    assert m_kg.canonical_value == 1500.0

    # 16 oz -> ~453.59 g
    m_oz = parse_measurement("16 oz")
    assert m_oz is not None
    assert m_oz.canonical_unit == "g"
    assert 453.0 < m_oz.canonical_value < 454.0

    # 2 lbs -> ~907.18 g
    m_lb = parse_measurement("2.0 lbs")
    assert m_lb is not None
    assert m_lb.canonical_unit == "g"
    assert 907.0 < m_lb.canonical_value < 908.0

    # Invalid input
    assert parse_measurement("not_a_measurement") is None


def test_mixed_length_volume_normalization() -> None:
    # Length: 10 inches -> 25.4 cm
    m_in = parse_measurement("10 inches")
    assert m_in is not None
    assert m_in.dimension == "length"
    assert m_in.canonical_unit == "cm"
    assert m_in.canonical_value == 25.4

    # Volume: 750 ml
    m_ml = parse_measurement("750 ml")
    assert m_ml is not None
    assert m_ml.dimension == "volume"
    assert m_ml.canonical_value == 750.0

    # Volume: 16 fl_oz -> ~473.18 ml
    m_floz = parse_measurement("16 fl_oz")
    assert m_floz is not None
    assert m_floz.dimension == "volume"
    assert 473.0 < m_floz.canonical_value < 474.0


def test_text_to_attribute_distillation() -> None:
    raw_desc = (
        "Ultra-lightweight marathon shoe engineered with carbon plate technology, "
        "fully waterproof upper, and a featherlight weight of 240g for race day."
    )
    attrs = extract_attributes_from_text(raw_desc, tags=("running", "marathon"))
    assert attrs.get("waterproof") is True
    assert attrs.get("carbon_plate") is True
    assert attrs.get("weight_g") == 240.0


def test_graceful_filter_relaxation_exact_matches() -> None:
    catalog = [
        Product(
            product_id="p1",
            title="Budget Running Shoe",
            description="Affordable road shoe",
            base_price=90.0,
            category="footwear",
            in_stock=True,
            tags=("running",),
        ),
        Product(
            product_id="p2",
            title="Premium Carbon Shoe",
            description="Pro racing shoe",
            base_price=180.0,
            category="footwear",
            in_stock=True,
            tags=("running", "carbon"),
        ),
    ]

    # Exact filter within budget
    res = filter_with_graceful_relaxation(catalog, ProductFilter(category="footwear", max_price=100.0))
    assert res.is_relaxed is False
    assert res.total_count == 1
    assert res.matched_products[0].product_id == "p1"
    assert res.relaxation_advice is None


def test_graceful_filter_relaxation_price_bottleneck() -> None:
    catalog = [
        Product(
            product_id="p1",
            title="AcousticPro ANC Headphones",
            description="Active noise cancelling wireless headphones",
            base_price=249.0,
            category="electronics",
            in_stock=True,
            tags=("audio", "anc"),
        ),
        Product(
            product_id="p2",
            title="Studio Master Reference Headphones",
            description="Open back reference headphones",
            base_price=399.0,
            category="electronics",
            in_stock=True,
            tags=("audio", "studio"),
        ),
    ]

    # Shopper requested budget under $200 in electronics (0 exact matches)
    res = filter_with_graceful_relaxation(catalog, ProductFilter(category="electronics", max_price=200.0))

    # Must NOT silently drop filter or return empty without diagnosis
    assert res.is_relaxed is True
    assert res.total_count == 2
    assert res.relaxation_advice is not None
    assert res.relaxation_advice.bottleneck_dimension == "max_price"
    assert "249.00" in res.relaxation_advice.suggested_threshold
    assert "No products found under budget of $200.00" in res.relaxation_advice.explanation
    # Returns closest item sorted first
    assert res.matched_products[0].product_id == "p1"
