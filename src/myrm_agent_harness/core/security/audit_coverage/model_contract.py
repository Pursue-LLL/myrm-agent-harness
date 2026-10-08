"""Application model contract validation for security audit findings.

[INPUT]
- ApplicationModel, AuditFinding.

[OUTPUT]
- Validation confirmation or UnsupportedFindingError.

[POS]
- Harness core security engine. Ensures audit conclusions are strictly supported
  by declared architectural models rather than speculative assertions.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.audit_coverage.types import (
    ApplicationModel,
    AuditFinding,
    UnsupportedFindingError,
)

logger = logging.getLogger(__name__)


class ApplicationModelContract:
    """Enforces that audit findings adhere to the declared application model boundaries."""

    def __init__(self, model: ApplicationModel) -> None:
        self._model = model

    @property
    def model(self) -> ApplicationModel:
        """Declared application model under audit."""
        return self._model

    def validate_finding(self, finding: AuditFinding) -> None:
        """Assert that finding category is supported by the application model."""
        if finding.category not in self._model.supported_finding_categories:
            raise UnsupportedFindingError(
                f"Unsupported Finding: Finding category '{finding.category}' is outside "
                f"the supported categories {self._model.supported_finding_categories} "
                f"of application model '{self._model.name}'."
            )

        # Ensure referenced entrypoint or boundary exists if stated
        if finding.application_model_ref:
            has_matching_boundary = any(
                finding.application_model_ref in ref
                for ref in (
                    *self._model.entrypoints,
                    *self._model.trust_boundaries,
                    *self._model.data_flows,
                )
            )
            if not has_matching_boundary:
                logger.warning(
                    "Finding '%s' references '%s' which is not explicitly modeled in '%s'.",
                    finding.finding_id,
                    finding.application_model_ref,
                    self._model.name,
                )
