"""Unit tests for EvidenceReadOnlyValidator.

[INPUT]
- myrm_agent_harness.agent.meta_tools.file_ops.validators.evidence_readonly_validator (POS: EvidenceReadOnlyValidator under test)
- myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context (POS: OperationContext, OperationType)

[OUTPUT]
- test_evidence_readonly_validator_allows_view: verify read operations are unaffected
- test_evidence_readonly_validator_allows_regular_write: verify non-evidence writes pass
- test_evidence_readonly_validator_blocks_evidence_write: verify evidence file mutation is blocked

[POS]
Harness Agent Layer — File Ops Meta Tools validator tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import (
    OperationType,
)
from myrm_agent_harness.agent.meta_tools.file_ops.validators.evidence_readonly_validator import (
    EvidenceReadOnlyValidator,
)


def _make_context(op: OperationType) -> MagicMock:
    ctx = MagicMock()
    ctx.operation = op
    return ctx


@pytest.mark.asyncio
async def test_evidence_readonly_validator_allows_view() -> None:
    validator = EvidenceReadOnlyValidator()
    ctx = _make_context(OperationType.VIEW)
    await validator.validate(ctx, "evidence/audit_log.json")


@pytest.mark.asyncio
async def test_evidence_readonly_validator_allows_regular_write() -> None:
    validator = EvidenceReadOnlyValidator()
    ctx = _make_context(OperationType.CREATE)
    await validator.validate(ctx, "src/components/Button.tsx")


@pytest.mark.asyncio
async def test_evidence_readonly_validator_blocks_evidence_write() -> None:
    validator = EvidenceReadOnlyValidator()
    ctx = _make_context(OperationType.CREATE)
    with pytest.raises(PermissionError, match="BLOCKED: 'evidence/step_1_receipt.json' resides in a read-only"):
        await validator.validate(ctx, "evidence/step_1_receipt.json")
