"""Unit tests for Semantic Layer RBAC & Private Fact Masking Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.semantic_rbac import (
    AccessModifier,
    PrivateFactExposureError,
    SemanticColumnDefinition,
    SemanticRbacEngine,
    SemanticRbacError,
    SemanticViewSchema,
    UserIdentityContext,
)


@pytest.fixture
def sales_view_engine() -> SemanticRbacEngine:
    engine = SemanticRbacEngine()
    schema = SemanticViewSchema(
        view_name="sales_orders",
        columns=(
            SemanticColumnDefinition("order_id", "string", AccessModifier.PUBLIC),
            SemanticColumnDefinition("tenant_id", "string", AccessModifier.PUBLIC),
            SemanticColumnDefinition("dept_id", "string", AccessModifier.PUBLIC),
            SemanticColumnDefinition("sale_amount", "float", AccessModifier.PUBLIC),
            # Sensitive columns: secret internal cost and confidential discount rate
            SemanticColumnDefinition("base_cost", "float", AccessModifier.PRIVATE_ACCESS),
            SemanticColumnDefinition("discount_pct", "float", AccessModifier.PRIVATE_ACCESS),
            # Restricted column: visible only to executives
            SemanticColumnDefinition(
                "executive_margin",
                "float",
                AccessModifier.RESTRICTED,
                allowed_roles=("cfo", "executive"),
            ),
        ),
    )
    engine.register_view(schema)
    return engine


def test_private_fact_projection_is_blocked(sales_view_engine: SemanticRbacEngine) -> None:
    """Test that directly projecting private_access columns is strictly blocked."""
    identity = UserIdentityContext(
        user_id="user-1",
        tenant_id="tenant-corp",
        dept_id="sales",
        role="sales_rep",
    )

    # Attempting to directly select base_cost raises PrivateFactExposureError
    with pytest.raises(PrivateFactExposureError, match="marked as private_access"):
        sales_view_engine.plan_query(
            view_name="sales_orders",
            requested_columns=["order_id", "base_cost"],
            aggregated_metrics=[],
            identity=identity,
        )


def test_restricted_column_role_authorization(sales_view_engine: SemanticRbacEngine) -> None:
    """Test role verification for restricted columns."""
    normal_identity = UserIdentityContext(
        user_id="user-2",
        tenant_id="tenant-corp",
        dept_id="sales",
        role="sales_rep",
    )
    cfo_identity = UserIdentityContext(
        user_id="user-3",
        tenant_id="tenant-corp",
        dept_id="finance",
        role="cfo",
    )

    # Normal user blocked
    with pytest.raises(SemanticRbacError, match="not authorized to project column"):
        sales_view_engine.plan_query(
            view_name="sales_orders",
            requested_columns=["order_id", "executive_margin"],
            aggregated_metrics=[],
            identity=normal_identity,
        )

    # CFO permitted
    plan_cfo = sales_view_engine.plan_query(
        view_name="sales_orders",
        requested_columns=["order_id", "executive_margin"],
        aggregated_metrics=[],
        identity=cfo_identity,
    )
    assert "executive_margin" in plan_cfo.projected_columns


def test_aggregation_over_private_access_permitted(sales_view_engine: SemanticRbacEngine) -> None:
    """Test mathematical aggregation over private_access columns is allowed without exposing details."""
    identity = UserIdentityContext(
        user_id="user-4",
        tenant_id="tenant-corp",
        dept_id="sales",
        role="sales_rep",
    )

    # SUM(base_cost) is permitted for computing totals
    plan = sales_view_engine.plan_query(
        view_name="sales_orders",
        requested_columns=[],
        aggregated_metrics=["SUM(base_cost)", "AVG(discount_pct)"],
        identity=identity,
    )
    assert plan.aggregated_metrics == ("SUM(base_cost)", "AVG(discount_pct)")
    assert "tenant_id = 'tenant-corp'" in plan.injected_predicates
    assert "dept_id = 'sales'" in plan.injected_predicates

    # Execute against sample data
    raw_data = [
        {"order_id": "1", "tenant_id": "tenant-corp", "dept_id": "sales", "base_cost": 40.0, "discount_pct": 0.10},
        {"order_id": "2", "tenant_id": "tenant-corp", "dept_id": "sales", "base_cost": 60.0, "discount_pct": 0.20},
        # Other dept
        {"order_id": "3", "tenant_id": "tenant-corp", "dept_id": "engineering", "base_cost": 500.0, "discount_pct": 0.05},
        # Other tenant
        {"order_id": "4", "tenant_id": "other-tenant", "dept_id": "sales", "base_cost": 999.0, "discount_pct": 0.50},
    ]

    results = sales_view_engine.execute_query(plan, raw_data, identity)
    assert len(results) == 1
    # Only orders 1 & 2 in tenant-corp & sales are aggregated: 40 + 60 = 100
    assert results[0]["SUM(base_cost)"] == 100.0
    assert results[0]["AVG(discount_pct)"] == 0.15


def test_identity_aware_row_filtering(sales_view_engine: SemanticRbacEngine) -> None:
    """Test dynamic injection of tenant and department row filters."""
    sales_identity = UserIdentityContext(
        user_id="user-5",
        tenant_id="tenant-corp",
        dept_id="sales",
        role="sales_rep",
        is_admin=False,
    )
    admin_identity = UserIdentityContext(
        user_id="admin-1",
        tenant_id="tenant-corp",
        dept_id="it",
        role="admin",
        is_admin=True,
    )

    raw_data = [
        {"order_id": "101", "tenant_id": "tenant-corp", "dept_id": "sales", "sale_amount": 200.0},
        {"order_id": "102", "tenant_id": "tenant-corp", "dept_id": "marketing", "sale_amount": 300.0},
        {"order_id": "103", "tenant_id": "other-tenant", "dept_id": "sales", "sale_amount": 500.0},
    ]

    # Sales rep only gets sales within tenant-corp
    plan_sales = sales_view_engine.plan_query("sales_orders", ["order_id", "sale_amount"], [], sales_identity)
    res_sales = sales_view_engine.execute_query(plan_sales, raw_data, sales_identity)
    assert len(res_sales) == 1
    assert res_sales[0]["order_id"] == "101"

    # Admin gets all departments within tenant-corp, but NOT other tenants
    plan_admin = sales_view_engine.plan_query("sales_orders", ["order_id", "sale_amount"], [], admin_identity)
    res_admin = sales_view_engine.execute_query(plan_admin, raw_data, admin_identity)
    assert len(res_admin) == 2
    order_ids = {r["order_id"] for r in res_admin}
    assert order_ids == {"101", "102"}
