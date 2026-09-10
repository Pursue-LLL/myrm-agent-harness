"""Merchant Price, Promotion, and Inventory Guardrail Enforcement Suite.

[INPUT]
- typing::Literal, Any
- pydantic::BaseModel, Field
- myrm_agent_harness.backends.commerce.types::Listing, ChangeType, PricingContext
- myrm_agent_harness.backends.commerce.exceptions::GuardrailViolationError, ChangeNotApplicable

[OUTPUT]
- GuardrailDecision: 门禁决策状态 ("passed" | "blocked" | "held")
- MerchantGuardrailConfig: 商家端风控门禁配置
- GuardrailViolation: 结构化单项违规指标与合规折中备选方案
- GuardrailCheckResult: 门禁总体检查结论与系统引导提示
- check_merchant_guardrails(): 暂存与生效双阶段独立防线执行器

[POS]
Harness-level commerce merchant safety guardrail engine.
Prevents catastrophic price crashes, excessive promotion depths, runaway restocks,
and unauthorised modifications to protected catalog fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from myrm_agent_harness.backends.commerce.exceptions import GuardrailViolationError
from myrm_agent_harness.backends.commerce.types import ChangeType, Listing, PricingContext

GuardrailDecision = Literal["passed", "blocked", "held"]


class MerchantGuardrailConfig(BaseModel):
    """Safety guardrail thresholds for merchant operations."""

    max_promotion_discount_pct: float = Field(
        default=30.0,
        ge=0.0,
        le=100.0,
        description="Maximum allowed promotion discount percentage (e.g., 30.0 = 30% off)",
    )
    max_price_drop_pct: float = Field(
        default=25.0,
        ge=0.0,
        le=100.0,
        description="Maximum allowed single price reduction percentage",
    )
    max_price_decrease_pct: float | None = Field(
        default=None,
        description="Alias for max_price_drop_pct, supports fractional ratio (e.g. 0.20) or percentage (20.0)",
    )
    enforce_floor_price: bool = Field(
        default=False,
        description="Whether to strictly enforce floor price bounds from pricing context",
    )
    max_price_increase_pct: float = Field(
        default=50.0,
        ge=0.0,
        description="Maximum allowed single price increase percentage",
    )
    max_restock_units: int = Field(
        default=1000,
        ge=1,
        description="Maximum allowed inventory restock units in a single proposal",
    )
    max_campaign_budget: float = Field(
        default=10000.0,
        ge=0.0,
        description="Maximum monetary budget permitted for a promotional campaign",
    )
    protected_fields: tuple[str, ...] = Field(
        default=("listing_id", "merchant_id", "created_at", "sku"),
        description="Fields strictly prohibited from being modified by staged proposals",
    )

    @property
    def effective_max_price_drop_pct(self) -> float:
        if self.max_price_decrease_pct is not None:
            if self.max_price_decrease_pct <= 1.0:
                return self.max_price_decrease_pct * 100.0
            return self.max_price_decrease_pct
        return self.max_price_drop_pct


GuardrailLimits = MerchantGuardrailConfig


class GuardrailViolation(BaseModel):
    """Detailed record of a guardrail violation with a compliant alternative."""

    field: str
    rule: str
    proposed_value: str
    threshold: str
    message: str
    compliant_alternative: str | None = None


class GuardrailCheckResult(BaseModel):
    """Overall outcome of running guardrail checks on a merchant proposal."""

    decision: GuardrailDecision
    allowed: bool
    violations: list[GuardrailViolation] = Field(default_factory=list)
    guidance_prompt: str | None = None


def check_merchant_guardrails(
    listing: Listing,
    change_type: ChangeType | None = None,
    proposed_values: dict[str, str | int | float] | tuple[tuple[str, str], ...] | None = None,
    config: MerchantGuardrailConfig | None = None,
    pricing_context: PricingContext | None = None,
    *,
    change: StagedChange | None = None,
    is_apply_phase: bool = False,
) -> GuardrailCheckResult:
    """Execute safety guardrail verification against a proposed listing change.

    Supports both positional `(listing, change_type, proposed_values, ...)` and
    `check_merchant_guardrails(change=..., listing=..., config=...)` signatures.
    """
    if change is not None:
        change_type = change.change_type
        proposed_values = change.proposed_values

    if change_type is None or proposed_values is None:
        raise ValueError("Either change or both change_type and proposed_values must be provided.")
    active_config = config or MerchantGuardrailConfig()
    violations: list[GuardrailViolation] = []

    # Normalize proposed values into a standard dict
    props: dict[str, str | int | float] = {}
    if isinstance(proposed_values, tuple):
        for k, v in proposed_values:
            props[k] = v
    elif isinstance(proposed_values, dict):
        props = dict(proposed_values)

    # Determine effective price drop percentage threshold
    if active_config.max_price_decrease_pct is not None:
        raw = active_config.max_price_decrease_pct
        effective_drop_pct = (raw * 100.0) if raw <= 1.0 else raw
    else:
        effective_drop_pct = active_config.max_price_drop_pct

    # 1. Protected Fields Immutability Gate
    for field_name in active_config.protected_fields:
        if field_name in props:
            violations.append(
                GuardrailViolation(
                    field=field_name,
                    rule="protected_fields_immutability",
                    proposed_value=str(props[field_name]),
                    threshold="READ_ONLY",
                    message=f"Field '{field_name}' is protected and strictly read-only.",
                    compliant_alternative=(
                        f"Omit '{field_name}' from the proposal; only mutable catalog fields can be modified."
                    ),
                )
            )

    # 2. Price Update Rules
    if change_type == ChangeType.PRICE_UPDATE:
        price_val = props.get("price") or props.get("new_price")
        if price_val is not None:
            try:
                new_price = float(price_val)
            except (ValueError, TypeError):
                violations.append(
                    GuardrailViolation(
                        field="price",
                        rule="valid_number",
                        proposed_value=str(price_val),
                        threshold="float > 0.0",
                        message=f"Proposed price '{price_val}' is not a valid positive number.",
                        compliant_alternative=None,
                    )
                )
                new_price = None

            if new_price is not None:
                current_price = listing.price
                if current_price > 0.0:
                    # Check Price Drop
                    if new_price < current_price:
                        drop_pct = ((current_price - new_price) / current_price) * 100.0
                        if drop_pct > effective_drop_pct:
                            min_compliant_price = round(
                                current_price * (1.0 - (effective_drop_pct / 100.0)),
                                2,
                            )
                            violations.append(
                                GuardrailViolation(
                                    field="price",
                                    rule="max_price_drop_pct",
                                    proposed_value=f"{new_price:.2f} (drop {drop_pct:.1f}%)",
                                    threshold=f"max drop {effective_drop_pct:.1f}%",
                                    message=(
                                        f"Price drop of {drop_pct:.1f}% exceeds maximum allowed price reduction limit of "
                                        f"{effective_drop_pct:.1f}%."
                                    ),
                                    compliant_alternative=(
                                        f"Propose a price of at least {min_compliant_price:.2f} to remain "
                                        f"within the {effective_drop_pct:.1f}% drop limit."
                                    ),
                                )
                            )

                    # Check Price Increase
                    elif new_price > current_price:
                        increase_pct = ((new_price - current_price) / current_price) * 100.0
                        if increase_pct > active_config.max_price_increase_pct:
                            max_compliant_price = round(
                                current_price * (1.0 + (active_config.max_price_increase_pct / 100.0)),
                                2,
                            )
                            violations.append(
                                GuardrailViolation(
                                    field="price",
                                    rule="max_price_increase_pct",
                                    proposed_value=f"{new_price:.2f} (increase {increase_pct:.1f}%)",
                                    threshold=f"max increase {active_config.max_price_increase_pct:.1f}%",
                                    message=(
                                        f"Price hike of {increase_pct:.1f}% exceeds maximum allowed limit of "
                                        f"{active_config.max_price_increase_pct:.1f}%."
                                    ),
                                    compliant_alternative=(
                                        f"Propose a price of at most {max_compliant_price:.2f} to remain "
                                        f"within the {active_config.max_price_increase_pct:.1f}% increase limit."
                                    ),
                                )
                            )

                # Check PricingContext absolute bounds if available
                if pricing_context is not None:
                    floor = pricing_context.floor_price if pricing_context.floor_price is not None else pricing_context.min_allowed_price
                    if floor > 0.0 and new_price < floor:
                        violations.append(
                            GuardrailViolation(
                                field="price",
                                rule="min_allowed_price",
                                proposed_value=f"{new_price:.2f}",
                                threshold=f"{floor:.2f}",
                                message=(
                                    f"Proposed price {new_price:.2f} violates profit margin policy; "
                                    f"minimum allowed price is {floor:.2f}."
                                ),
                                compliant_alternative=(
                                    f"Propose a price of at least {floor:.2f}."
                                ),
                            )
                        )
                    ceiling = pricing_context.ceiling_price if pricing_context.ceiling_price is not None else pricing_context.max_allowed_price
                    if ceiling > 0.0 and new_price > ceiling:
                        violations.append(
                            GuardrailViolation(
                                field="price",
                                rule="max_allowed_price",
                                proposed_value=f"{new_price:.2f}",
                                threshold=f"{ceiling:.2f}",
                                message=(
                                    f"Proposed price {new_price:.2f} exceeds ceiling; "
                                    f"maximum allowed price is {ceiling:.2f}."
                                ),
                                compliant_alternative=(
                                    f"Propose a price of at most {ceiling:.2f}."
                                ),
                            )
                        )

    # 3. Promotion Rules
    elif change_type == ChangeType.PROMOTION:
        discount_val = props.get("discount_pct") or props.get("discount_percentage")
        if discount_val is not None:
            try:
                discount_pct = float(discount_val)
            except (ValueError, TypeError):
                violations.append(
                    GuardrailViolation(
                        field="discount_pct",
                        rule="valid_number",
                        proposed_value=str(discount_val),
                        threshold="float >= 0.0",
                        message=f"Discount percentage '{discount_val}' is invalid.",
                        compliant_alternative=None,
                    )
                )
                discount_pct = None

            if discount_pct is not None and discount_pct > active_config.max_promotion_discount_pct:
                violations.append(
                    GuardrailViolation(
                        field="discount_pct",
                        rule="max_promotion_discount_pct",
                        proposed_value=f"{discount_pct:.1f}%",
                        threshold=f"{active_config.max_promotion_discount_pct:.1f}%",
                        message=(
                            f"Proposed promotion discount {discount_pct:.1f}% exceeds maximum allowed limit "
                            f"of {active_config.max_promotion_discount_pct:.1f}%."
                        ),
                        compliant_alternative=(
                            f"Propose a discount percentage of at most "
                            f"{active_config.max_promotion_discount_pct:.1f}%."
                        ),
                    )
                )

        budget_val = props.get("campaign_budget") or props.get("budget")
        if budget_val is not None:
            try:
                budget = float(budget_val)
            except (ValueError, TypeError):
                violations.append(
                    GuardrailViolation(
                        field="campaign_budget",
                        rule="valid_number",
                        proposed_value=str(budget_val),
                        threshold="float >= 0.0",
                        message=f"Campaign budget '{budget_val}' is invalid.",
                        compliant_alternative=None,
                    )
                )
                budget = None

            if budget is not None and budget > active_config.max_campaign_budget:
                violations.append(
                    GuardrailViolation(
                        field="campaign_budget",
                        rule="max_campaign_budget",
                        proposed_value=f"{budget:.2f}",
                        threshold=f"{active_config.max_campaign_budget:.2f}",
                        message=(
                            f"Proposed campaign budget {budget:.2f} exceeds cap of "
                            f"{active_config.max_campaign_budget:.2f}."
                        ),
                        compliant_alternative=(
                            f"Set the campaign budget to at most {active_config.max_campaign_budget:.2f}."
                        ),
                    )
                )

    # 4. Inventory Restock Rules
    elif change_type == ChangeType.RESTOCK:
        units_val = props.get("units") or props.get("quantity") or props.get("restock_units")
        if units_val is not None:
            try:
                units = int(units_val)
            except (ValueError, TypeError):
                violations.append(
                    GuardrailViolation(
                        field="units",
                        rule="valid_integer",
                        proposed_value=str(units_val),
                        threshold="integer > 0",
                        message=f"Restock quantity '{units_val}' is invalid.",
                        compliant_alternative=None,
                    )
                )
                units = None

            if units is not None and units > active_config.max_restock_units:
                violations.append(
                    GuardrailViolation(
                        field="units",
                        rule="max_restock_units",
                        proposed_value=str(units),
                        threshold=str(active_config.max_restock_units),
                        message=(
                            f"Proposed restock quantity {units} exceeds safety ceiling of "
                            f"{active_config.max_restock_units} units."
                        ),
                        compliant_alternative=(
                            f"Restock at most {active_config.max_restock_units} units in this batch."
                        ),
                    )
                )

    # 5. Synthesize Guidance Prompt and Result
    if violations:
        phase_label = "Apply" if is_apply_phase else "Stage"
        lines = [
            f"[{phase_label} Guardrail Blocked] {len(violations)} safety rule(s) were breached:"
        ]
        for v in violations:
            lines.append(f"- Field '{v.field}' violated '{v.rule}': {v.message}")
            if v.compliant_alternative:
                lines.append(f"  Suggested Compliant Alternative: {v.compliant_alternative}")
        lines.append(
            "\nAgent Guidance: Clearly explain each violation to the merchant operator and "
            "propose the compliant alternative(s) listed above."
        )

        guidance_text = "\n".join(lines)
        return GuardrailCheckResult(
            decision="blocked",
            allowed=False,
            violations=violations,
            guidance_prompt=guidance_text,
        )

    return GuardrailCheckResult(
        decision="passed",
        allowed=True,
        violations=[],
        guidance_prompt=None,
    )


# Aliases for roadmap and test suite parity
GuardrailLimits = MerchantGuardrailConfig
check_guardrails = check_merchant_guardrails


def validate_protected_fields(
    payload: dict[str, object],
    protected_fields: tuple[str, ...] | None = None,
) -> tuple[bool, str | None]:
    """Validate that mutable proposals do not tamper with protected immutable fields."""
    protected = protected_fields or ("cost_price", "supplier_id", "listing_id", "merchant_id", "sku")
    blocked = [f for f in protected if f in payload]
    if blocked:
        return False, f"Protected fields cannot be modified: {', '.join(blocked)}"
    return True, None


def evaluate_options_explosion(
    listing: object,
    payload: dict[str, object],
) -> tuple[bool, str | None]:
    """Verify that modifications to multi-variant products explicitly target a specific variant."""
    product = getattr(listing, "product", None)
    if product is not None and getattr(product, "variants", None):
        target_variant_id = payload.get("variant_id")
        if not target_variant_id:
            return False, "Modifications to products with options must explicitly target a specific 'variant_id' to prevent ambiguous options explosion."
        variants = getattr(product, "variants", ())
        variant_ids = {getattr(v, "variant_id", None) for v in variants}
        if target_variant_id not in variant_ids:
            prod_id = getattr(product, "product_id", "unknown")
            return False, f"Variant '{target_variant_id}' not found on product '{prod_id}'."
    return True, None


