"""Agent-Driven Memory Paging Engine with cursor pagination and token budget guards."""

import base64
import json
from collections.abc import Sequence

from .gateway import HardBoundaryScopeGateway
from .models import (
    HardScopeContext,
    MemoryPageQuery,
    MemoryPageRecord,
    MemoryPageResult,
    PagingBudgetExceededError,
    PagingBudgetPolicy,
)


class AgentMemoryPagingEngine:
    """Provides cursor-based active pagination over memory with hard boundary and budget guards."""

    def __init__(self, gateway: HardBoundaryScopeGateway | None = None) -> None:
        """Initialize engine with boundary gateway and in-memory stores."""
        self._gateway = gateway or HardBoundaryScopeGateway()
        self._records: list[MemoryPageRecord] = []
        self._session_budgets: dict[str, PagingBudgetPolicy] = {}

    @property
    def total_records(self) -> int:
        """Return total record count across all scopes."""
        return len(self._records)

    def insert_record(self, record: MemoryPageRecord) -> str:
        """Insert a memory record into the store."""
        self._records.append(record)
        return record.record_id

    def insert_records(self, records: Sequence[MemoryPageRecord]) -> int:
        """Insert multiple records."""
        self._records.extend(records)
        return len(records)

    def get_session_budget(
        self,
        session_id: str,
        default_policy: PagingBudgetPolicy | None = None,
    ) -> PagingBudgetPolicy:
        """Retrieve active budget tracking state for a given session."""
        if session_id not in self._session_budgets:
            self._session_budgets[session_id] = (
                default_policy.model_copy() if default_policy else PagingBudgetPolicy()
            )
        return self._session_budgets[session_id]

    def set_session_budget_policy(self, session_id: str, policy: PagingBudgetPolicy) -> None:
        """Explicitly override budget policy for a session."""
        self._session_budgets[session_id] = policy

    def query_page(
        self,
        query: MemoryPageQuery,
        context: HardScopeContext,
        budget_policy: PagingBudgetPolicy | None = None,
    ) -> MemoryPageResult:
        """Execute a cursor-paginated memory exploration query within physical boundary limits.

        Args:
            query: Paging request with cursor, size, and filters.
            context: Physical boundary authentication context.
            budget_policy: Optional custom budget policy for this session.

        Returns:
            MemoryPageResult containing records and next_cursor.

        Raises:
            AccessViolationError: If boundary tampering is detected.
            PagingBudgetExceededError: If session quota is exceeded.
        """
        # 1. Enforce hard physical boundary via security gateway
        enforced_ctx = self._gateway.validate_and_enforce_scope(query, context)

        # 2. Check sliding token and query budget
        budget = self.get_session_budget(enforced_ctx.session_id, budget_policy)
        if budget.used_pages >= budget.max_pages_per_session:
            raise PagingBudgetExceededError(
                f"Session '{enforced_ctx.session_id}' exceeded maximum page query allowance "
                f"({budget.used_pages}/{budget.max_pages_per_session})."
            )
        if budget.used_tokens >= budget.max_tokens_per_session:
            raise PagingBudgetExceededError(
                f"Session '{enforced_ctx.session_id}' exceeded cumulative token budget "
                f"({budget.used_tokens}/{budget.max_tokens_per_session})."
            )

        # 3. Filter strictly within physical boundary
        matching = [
            r for r in self._records
            if r.scope.tenant_id == enforced_ctx.tenant_id
            and r.scope.project_id == enforced_ctx.project_id
        ]

        # Apply optional text search
        if query.query_text:
            needle = query.query_text.lower().strip()
            matching = [r for r in matching if needle in r.content.lower()]

        # Apply optional tag filtering
        if query.filter_tags:
            tag_set = {t.lower().strip() for t in query.filter_tags}
            matching = [
                r for r in matching
                if tag_set.issubset({rt.lower().strip() for rt in r.tags})
            ]

        # Sort stably by creation timestamp ascending
        matching.sort(key=lambda r: r.created_at)

        # 4. Resolve offset from cursor
        offset = self._decode_cursor(query.cursor)
        page_size = query.page_size
        page_records = matching[offset : offset + page_size]

        # 5. Compute token cost and deduct budget
        page_token_cost = sum(r.token_count for r in page_records)
        budget.used_pages += 1
        budget.used_tokens += page_token_cost

        # 6. Generate next cursor
        has_more = (offset + page_size) < len(matching)
        next_cursor = self._encode_cursor(offset + page_size) if has_more else None
        page_index = (offset // page_size) if page_size > 0 else 0

        return MemoryPageResult(
            records=page_records,
            next_cursor=next_cursor,
            has_more=has_more,
            page_token_cost=page_token_cost,
            page_index=page_index,
        )

    def _encode_cursor(self, offset: int) -> str:
        """Encode numeric offset into opaque base64 string."""
        payload = json.dumps({"offset": offset}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")

    def _decode_cursor(self, cursor: str | None) -> int:
        """Decode opaque cursor back to integer offset."""
        if not cursor:
            return 0
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
            data = json.loads(raw)
            return max(0, int(data.get("offset", 0)))
        except (ValueError, KeyError, TypeError):
            return 0
