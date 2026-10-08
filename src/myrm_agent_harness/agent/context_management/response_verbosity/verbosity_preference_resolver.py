# [INPUT]: ResponseVerbosityLevel, VerbosityBudgetConfig, VerbositySource
# [OUTPUT]: VerbosityPreferenceResolver
# [POS]: agent/context_management/response_verbosity/verbosity_preference_resolver.py

"""Cascade resolver determining effective response verbosity across multi-tier preferences.

[INPUT]
- ResponseVerbosityLevel, VerbositySource: Preference enums.
- VerbosityBudgetConfig: Configuration supplying baseline system defaults.

[OUTPUT]
- VerbosityPreferenceResolver: Hierarchically resolves effective tier from turn, session, profile, and system levels.

[POS]
Preference resolution layer in response verbosity subsystem supporting smooth UI and Agent overrides.
"""

from __future__ import annotations

from .verbosity_types import (
    ResponseVerbosityLevel,
    VerbosityBudgetConfig,
    VerbositySource,
)


class VerbosityPreferenceResolver:
    """Resolves active verbosity tier using strict hierarchy: Turn > Session > Profile > System."""

    def __init__(self, config: VerbosityBudgetConfig | None = None) -> None:
        self._config = config or VerbosityBudgetConfig()

    def resolve(
        self,
        turn_override: ResponseVerbosityLevel | str | None = None,
        session_preference: ResponseVerbosityLevel | str | None = None,
        profile_default: ResponseVerbosityLevel | str | None = None,
    ) -> tuple[ResponseVerbosityLevel, VerbositySource]:
        """Resolve effective verbosity level and identify its decision source.

        Hierarchy:
        1. turn_override (highest, per-message composer pill)
        2. session_preference (per-chat sticky preference)
        3. profile_default (agent role baseline, e.g. Auditor=Low, Tutor=High)
        4. system_default (framework configuration baseline)

        Returns:
            Tuple of (resolved_level, source_provenance).
        """
        # 1. Turn override
        if turn_override is not None:
            parsed = self._coerce_level(turn_override)
            if parsed is not None:
                return parsed, VerbositySource.TURN_OVERRIDE

        # 2. Session preference
        if session_preference is not None:
            parsed = self._coerce_level(session_preference)
            if parsed is not None:
                return parsed, VerbositySource.SESSION_PREFERENCE

        # 3. Profile default
        if profile_default is not None:
            parsed = self._coerce_level(profile_default)
            if parsed is not None:
                return parsed, VerbositySource.PROFILE_DEFAULT

        # 4. System default fallback
        return self._config.default_level, VerbositySource.SYSTEM_DEFAULT

    @staticmethod
    def _coerce_level(raw: ResponseVerbosityLevel | str) -> ResponseVerbosityLevel | None:
        """Safely coerce string or enum into a valid ResponseVerbosityLevel."""
        if isinstance(raw, ResponseVerbosityLevel):
            return raw
        val = raw.strip().lower()
        try:
            return ResponseVerbosityLevel(val)
        except ValueError:
            return None
