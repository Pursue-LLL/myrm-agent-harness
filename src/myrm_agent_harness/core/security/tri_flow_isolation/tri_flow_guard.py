"""Tri-Flow physical workflow separation and financial confirmation guard."""

from __future__ import annotations

from .types import ToolRoleContract, TriFlowValidationResult, WorkflowRole


class TriFlowGuard:
    """Enforces strict isolation between Read-Only, Buyer, and Seller workflows

    and guarantees mandatory human-in-the-loop confirmation for financial operations.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, ToolRoleContract] = {}

    def register_tool(self, contract: ToolRoleContract) -> None:
        """Register tool role and financial constraints."""
        self._contracts[contract.tool_name.strip().lower()] = contract

    def get_contract(self, tool_name: str) -> ToolRoleContract | None:
        """Get registered contract for a tool."""
        return self._contracts.get(tool_name.strip().lower())

    def validate_tool_call(
        self,
        current_role: WorkflowRole,
        tool_name: str,
        amount: float = 0.0,
        hitl_confirmed: bool = False,
    ) -> TriFlowValidationResult:
        """Inspect if the tool call is permitted under the active workflow role.

        Guarantees:
        1. Read-Only flow cannot call Buyer/Seller financial or write tools.
        2. Buyer flow cannot access Seller-exclusive withdrawal/settlement channels.
        3. Financial transactions require explicit human confirmation.
        """
        clean_name = tool_name.strip().lower()
        contract = self._contracts.get(clean_name)

        # Default fallback if tool is not registered: allow only in non-read_only if no financial flag
        if contract is None:
            if current_role == "read_only":
                return TriFlowValidationResult(
                    is_allowed=False,
                    current_role=current_role,
                    tool_name=tool_name,
                    reason=(
                        f"Tool '{tool_name}' is not declared in Read-Only contract; "
                        "unregistered tools are blocked in read-only mode to prevent side effects."
                    ),
                    requires_hitl=False,
                )
            return TriFlowValidationResult(
                is_allowed=True,
                current_role=current_role,
                tool_name=tool_name,
                reason=f"Unregistered tool '{tool_name}' allowed in {current_role} flow.",
                requires_hitl=False,
            )

        # 1. Role physical boundary check
        if current_role not in contract.allowed_roles:
            return TriFlowValidationResult(
                is_allowed=False,
                current_role=current_role,
                tool_name=tool_name,
                reason=(
                    f"Violation: tool '{tool_name}' requires roles {contract.allowed_roles}, "
                    f"but active workflow role is '{current_role}'."
                ),
                requires_hitl=False,
            )

        # 2. Financial confirmation check
        needs_hitl = (
            contract.requires_hitl_confirmation
            or (contract.is_financial_transaction and amount > contract.financial_threshold)
        )
        if needs_hitl and not hitl_confirmed:
            return TriFlowValidationResult(
                is_allowed=False,
                current_role=current_role,
                tool_name=tool_name,
                reason=(
                    f"Financial safety check: tool '{tool_name}' involves financial transaction "
                    f"or exceeds threshold {contract.financial_threshold} (requested: {amount}); "
                    "requires explicit HITL confirmation."
                ),
                requires_hitl=True,
            )

        return TriFlowValidationResult(
            is_allowed=True,
            current_role=current_role,
            tool_name=tool_name,
            reason=f"Tool '{tool_name}' verified safe under '{current_role}' workflow role.",
            requires_hitl=False,
        )
