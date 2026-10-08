"""Registry for Irreversible External Write Tool Contracts."""

from __future__ import annotations

import threading

from .types import IrreversibleWriteContract, RiskLevel, WriteDomain

_STANDARD_CONTRACTS: list[IrreversibleWriteContract] = [
    # 1. Email domain
    IrreversibleWriteContract(
        tool_name="send_email",
        domain=WriteDomain.EMAIL,
        description="Send outgoing email to external recipients",
        default_risk_level=RiskLevel.HIGH,
    ),
    IrreversibleWriteContract(
        tool_name="mail_send",
        domain=WriteDomain.EMAIL,
        description="SMTP or API email dispatcher",
        default_risk_level=RiskLevel.HIGH,
    ),
    # 2. Git push domain
    IrreversibleWriteContract(
        tool_name="git_push",
        domain=WriteDomain.GIT_PUSH,
        description="Push commits or branches to remote Git repository",
        default_risk_level=RiskLevel.HIGH,
    ),
    IrreversibleWriteContract(
        tool_name="git_force_push",
        domain=WriteDomain.GIT_PUSH,
        description="Force push commits destroying remote history",
        default_risk_level=RiskLevel.CRITICAL,
    ),
    # 3. Payment domain
    IrreversibleWriteContract(
        tool_name="stripe_charge",
        domain=WriteDomain.PAYMENT,
        description="Initiate credit card or balance charge via Stripe",
        default_risk_level=RiskLevel.CRITICAL,
    ),
    IrreversibleWriteContract(
        tool_name="payment_transfer",
        domain=WriteDomain.PAYMENT,
        description="Transfer fiat or digital assets to external account",
        default_risk_level=RiskLevel.CRITICAL,
    ),
    # 4. Database write domain
    IrreversibleWriteContract(
        tool_name="sql_execute_write",
        domain=WriteDomain.DATABASE_WRITE,
        description="Execute mutating DDL/DML on remote database",
        default_risk_level=RiskLevel.HIGH,
    ),
    IrreversibleWriteContract(
        tool_name="db_drop_table",
        domain=WriteDomain.DATABASE_WRITE,
        description="Drop or truncate remote database tables",
        default_risk_level=RiskLevel.CRITICAL,
    ),
    # 5. IM broadcast domain
    IrreversibleWriteContract(
        tool_name="slack_broadcast",
        domain=WriteDomain.IM_BROADCAST,
        description="Broadcast message to public Slack channels",
        default_risk_level=RiskLevel.MEDIUM,
    ),
    IrreversibleWriteContract(
        tool_name="feishu_broadcast",
        domain=WriteDomain.IM_BROADCAST,
        description="Broadcast message to Feishu public group chats",
        default_risk_level=RiskLevel.MEDIUM,
    ),
]


class IrreversibleWriteContractRegistry:
    """Thread-safe registry of tools that cause irreversible external side effects."""

    def __init__(self, load_defaults: bool = True) -> None:
        self._lock = threading.Lock()
        self._contracts: dict[str, IrreversibleWriteContract] = {}
        if load_defaults:
            for contract in _STANDARD_CONTRACTS:
                self._contracts[contract.tool_name.lower()] = contract

    def register(self, contract: IrreversibleWriteContract) -> None:
        """Register or update an irreversible write tool contract."""
        with self._lock:
            self._contracts[contract.tool_name.lower()] = contract

    def unregister(self, tool_name: str) -> bool:
        """Remove a contract from registry."""
        with self._lock:
            return self._contracts.pop(tool_name.lower(), None) is not None

    def find_contract(self, tool_name: str) -> IrreversibleWriteContract | None:
        """Find matching contract for tool name."""
        with self._lock:
            return self._contracts.get(tool_name.lower().strip())

    def is_irreversible_write(self, tool_name: str) -> bool:
        """Check whether the tool is registered as an irreversible write operation."""
        return self.find_contract(tool_name) is not None

    def list_contracts(self) -> list[IrreversibleWriteContract]:
        """List all registered contracts."""
        with self._lock:
            return list(self._contracts.values())
