"""Semantic RBAC Engine for Dynamic Row-Level Filtering & Column-Level Private Fact Masking.

Guarantees:
1. Column security: private_access columns cannot be projected directly.
2. Row security: automatically injects tenant and department filters based on identity.
3. Safe aggregation: mathematical metrics over private facts (e.g. SUM, AVG) are permitted
   without exposing individual raw rows.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence

from myrm_agent_harness.core.security.semantic_rbac.types import (
    AccessModifier,
    JsonScalar,
    PrivateFactExposureError,
    SemanticQueryPlan,
    SemanticRbacError,
    SemanticViewSchema,
    UserIdentityContext,
)


class SemanticRbacEngine:
    """Engine enforcing row and column security over semantic query plans."""

    def __init__(self) -> None:
        self._views: dict[str, SemanticViewSchema] = {}

    def register_view(self, schema: SemanticViewSchema) -> None:
        """Register a governed semantic view schema."""
        self._views[schema.view_name] = schema

    def get_view(self, view_name: str) -> SemanticViewSchema | None:
        """Fetch registered view schema by name."""
        return self._views.get(view_name)

    def plan_query(
        self,
        view_name: str,
        requested_columns: Sequence[str],
        aggregated_metrics: Sequence[str],
        identity: UserIdentityContext,
    ) -> SemanticQueryPlan:
        """Generate a safe, identity-aware semantic query plan."""
        schema = self.get_view(view_name)
        if schema is None:
            raise SemanticRbacError(f"Semantic view '{view_name}' is not registered")

        # 1. Column-level projection validation
        for col_name in requested_columns:
            col = schema.get_column(col_name)
            if col is None:
                raise SemanticRbacError(
                    f"Column '{col_name}' does not exist in semantic view '{view_name}'"
                )

            # Check private_access modifier
            if col.access_modifier == AccessModifier.PRIVATE_ACCESS:
                raise PrivateFactExposureError(
                    f"⚠️ Access Denied: Column '{col_name}' in view '{view_name}' is marked as "
                    "private_access. It cannot be directly projected as individual detail and is "
                    "restricted solely to aggregate calculations."
                )

            # Check restricted modifier against roles
            if (
                col.access_modifier == AccessModifier.RESTRICTED
                and not identity.is_admin
                and identity.role not in col.allowed_roles
            ):
                raise SemanticRbacError(
                        f"⚠️ Access Denied: Role '{identity.role}' is not authorized to project "
                        f"column '{col_name}' in view '{view_name}'"
                    )

        # 2. Aggregated metrics validation (private_access columns allowed inside aggregate formulas)
        for metric_expr in aggregated_metrics:
            # Extract column names referenced in metric expression like SUM(base_cost)
            referenced_cols = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", metric_expr)
            func_names = {"sum", "avg", "count", "min", "max", "round"}
            for ref in referenced_cols:
                if ref.lower() not in func_names:
                    col = schema.get_column(ref)
                    if col is None:
                        raise SemanticRbacError(
                            f"Metric '{metric_expr}' references unknown column '{ref}'"
                        )

        # 3. Dynamic row-level predicates injection based on identity
        injected_predicates: list[str] = [
            f"{schema.tenant_column} = '{identity.tenant_id}'"
        ]
        if not identity.is_admin:
            injected_predicates.append(f"{schema.dept_column} = '{identity.dept_id}'")

        # 4. Construct governed SQL string
        select_parts = list(requested_columns) + list(aggregated_metrics)
        select_clause = ", ".join(select_parts) if select_parts else "*"
        where_clause = " AND ".join(injected_predicates)
        sql = f"SELECT {select_clause} FROM {view_name} WHERE {where_clause}"

        return SemanticQueryPlan(
            query_id=f"sqp-{uuid.uuid4().hex[:10]}",
            target_view=view_name,
            projected_columns=tuple(requested_columns),
            aggregated_metrics=tuple(aggregated_metrics),
            injected_predicates=tuple(injected_predicates),
            raw_sql=sql,
        )

    def execute_query(
        self,
        plan: SemanticQueryPlan,
        raw_rows: Sequence[Mapping[str, JsonScalar]],
        identity: UserIdentityContext,
    ) -> list[dict[str, JsonScalar]]:
        """Filter raw data according to identity predicates and project authorized fields."""
        schema = self.get_view(plan.target_view)
        if schema is None:
            raise SemanticRbacError(f"View '{plan.target_view}' not registered")

        # 1. Apply identity row-level filtering
        matched_rows: list[Mapping[str, JsonScalar]] = []
        for row in raw_rows:
            if row.get(schema.tenant_column) != identity.tenant_id:
                continue
            if not identity.is_admin and row.get(schema.dept_column) != identity.dept_id:
                continue
            matched_rows.append(row)

        # 2. Case: Pure aggregate query (e.g. SUM(base_cost))
        if plan.aggregated_metrics and not plan.projected_columns:
            agg_result: dict[str, JsonScalar] = {}
            for metric in plan.aggregated_metrics:
                match = re.match(r"(?i)(sum|avg|count|min|max)\(([a-zA-Z0-9_]+)\)", metric)
                if match:
                    func_name, col_name = match.group(1).upper(), match.group(2)
                    values = [
                        float(r[col_name])  # type: ignore[arg-type]
                        for r in matched_rows
                        if r.get(col_name) is not None
                    ]
                    if func_name == "SUM":
                        agg_result[metric] = round(sum(values), 2)
                    elif func_name == "AVG":
                        agg_result[metric] = round(sum(values) / len(values), 2) if values else 0.0
                    elif func_name == "COUNT":
                        agg_result[metric] = len(matched_rows)
                    elif func_name == "MIN":
                        agg_result[metric] = min(values) if values else 0.0
                    elif func_name == "MAX":
                        agg_result[metric] = max(values) if values else 0.0
                else:
                    agg_result[metric] = len(matched_rows)
            return [agg_result]

        # 3. Case: Row projection with masking
        projected_results: list[dict[str, JsonScalar]] = []
        for row in matched_rows:
            item: dict[str, JsonScalar] = {}
            for col in plan.projected_columns:
                item[col] = row.get(col)
            projected_results.append(item)

        return projected_results
