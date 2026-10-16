"""Denial diagnostic package: reason codes, allowed alternatives and the four resolution branches behind a denial message.

[INPUT]
- .diagnostic_reporter::DenialDiagnosticReporter (POS: Builds the diagnostic of one denial.)
- .types::DenialDiagnosticPayload, DenialReasonCodeEnum, ResolutionBranchEnum (POS: Data shapes of a denial diagnostic.)

[OUTPUT]
- DenialDiagnosticReporter, DenialDiagnosticPayload, DenialReasonCodeEnum, ResolutionBranchEnum: the package's public API

[POS]
Entry of the denial diagnostic package; keeps no state.
"""

from __future__ import annotations

from .diagnostic_reporter import DenialDiagnosticReporter
from .types import (
    DenialDiagnosticPayload,
    DenialReasonCodeEnum,
    ResolutionBranchEnum,
)

__all__ = [
    "DenialDiagnosticPayload",
    "DenialDiagnosticReporter",
    "DenialReasonCodeEnum",
    "ResolutionBranchEnum",
]
