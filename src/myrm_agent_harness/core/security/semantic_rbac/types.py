"""Types and contracts for Semantic Layer RBAC, Column Access Modifiers & Row Filtering.

Enforces:
1. Column access modifiers (PUBLIC vs PRIVATE_ACCESS for secret base costs / salaries).
2. Identity-aware row-level predicates injection (tenant, dept, role).
3. Private fact exposure prevention and mathematical aggregation isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class AccessModifier(StrEnum):
    """Column-level access modifier governing projection and visibility."""

    PUBLIC = "PUBLIC"
    PRIVATE_ACCESS = "PRIVATE_ACCESS"
    RESTRICTED = "RESTRICTED"


@dataclass(frozen=True)
class UserIdentityContext:
    """Caller identity credentials used to evaluate semantic access control."""

    user_id: str
    tenant_id: str
    dept_id: str
    role: str
    is_admin: bool = False


@dataclass(frozen=True)
class SemanticColumnDefinition:
    """Definition of a column in a governed semantic view."""

    name: str
    data_type: str
    access_modifier: AccessModifier = AccessModifier.PUBLIC
    allowed_roles: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class SemanticViewSchema:
    """Governed schema of a semantic entity view."""

    view_name: str
    columns: tuple[SemanticColumnDefinition, ...]
    tenant_column: str = "tenant_id"
    dept_column: str = "dept_id"

    def get_column(self, name: str) -> SemanticColumnDefinition | None:
        """Find a column definition by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None


@dataclass(frozen=True)
class SemanticQueryPlan:
    """Governed query execution plan with row-level predicates and column projections."""

    query_id: str
    target_view: str
    projected_columns: tuple[str, ...]
    aggregated_metrics: tuple[str, ...]
    injected_predicates: tuple[str, ...]
    raw_sql: str


class SemanticRbacError(Exception):
    """Base error for semantic layer RBAC and security."""


class PrivateFactExposureError(SemanticRbacError):
    """Raised when an unauthorized query attempts to directly project private_access columns."""


class UnauthorizedRowAccessError(SemanticRbacError):
    """Raised when query attempts to bypass identity row-level filtering."""
