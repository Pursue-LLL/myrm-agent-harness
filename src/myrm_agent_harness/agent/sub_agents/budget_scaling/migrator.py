"""Zero-disruption configuration upgrade migrator for subagents.

Detects legacy uncustomized defaults (e.g. concurrency in {3, 5}, turns in {25, 50})
and smoothly lifts them to modern industrial-grade defaults while 100% preserving
any user-customized configurations.

[INPUT]
- typing
- types

[OUTPUT]
- ConfigUpgradeMigrator

[POS]
Zero-disruption configuration upgrade migrator for subagents.
"""

from typing import cast

from .types import (
    DEFAULT_MAX_CHILDREN_PER_AGENT,
    DEFAULT_MAX_DESCENDANTS_PER_RUN,
    DEFAULT_SCALED_CONCURRENCY,
    DEFAULT_SCALED_MAX_TURNS,
    LEGACY_DEFAULT_CONCURRENCY,
    LEGACY_DEFAULT_MAX_TURNS,
    ConfigMigrationResult,
)


class ConfigUpgradeMigrator:
    """Detects and smoothly migrates legacy subagent execution quotas."""

    @staticmethod
    def migrate_config_dict(raw_config: dict[str, object]) -> tuple[dict[str, object], ConfigMigrationResult]:
        """Inspect and adapt a subagent configuration dictionary.

        Returns:
            A tuple of (migrated_dict, migration_result).
        """
        data = dict(raw_config)
        reasons: list[str] = []
        concurrency_migrated = False
        max_turns_migrated = False

        # 1. Concurrency limit inspection & migration
        raw_concurrency = data.get("concurrency_limit")
        old_concurrency: int | None = None
        new_concurrency: int = DEFAULT_SCALED_CONCURRENCY

        if raw_concurrency is None:
            data["concurrency_limit"] = DEFAULT_SCALED_CONCURRENCY
            new_concurrency = DEFAULT_SCALED_CONCURRENCY
        else:
            try:
                parsed_c = int(cast(int | str, raw_concurrency))
                old_concurrency = parsed_c
                if parsed_c in LEGACY_DEFAULT_CONCURRENCY:
                    data["concurrency_limit"] = DEFAULT_SCALED_CONCURRENCY
                    new_concurrency = DEFAULT_SCALED_CONCURRENCY
                    concurrency_migrated = True
                    reasons.append(
                        f"Lifted legacy default concurrency_limit ({parsed_c}) "
                        f"to scaled default ({DEFAULT_SCALED_CONCURRENCY})"
                    )
                else:
                    new_concurrency = parsed_c
            except (ValueError, TypeError):
                data["concurrency_limit"] = DEFAULT_SCALED_CONCURRENCY
                new_concurrency = DEFAULT_SCALED_CONCURRENCY

        # 2. Max turns inspection & migration
        raw_turns = data.get("max_turns")
        old_max_turns: int | None = None
        new_max_turns: int = DEFAULT_SCALED_MAX_TURNS

        if raw_turns is None:
            data["max_turns"] = DEFAULT_SCALED_MAX_TURNS
            new_max_turns = DEFAULT_SCALED_MAX_TURNS
        else:
            try:
                parsed_t = int(cast(int | str, raw_turns))
                old_max_turns = parsed_t
                if parsed_t in LEGACY_DEFAULT_MAX_TURNS:
                    data["max_turns"] = DEFAULT_SCALED_MAX_TURNS
                    new_max_turns = DEFAULT_SCALED_MAX_TURNS
                    max_turns_migrated = True
                    reasons.append(
                        f"Lifted legacy default max_turns ({parsed_t}) "
                        f"to scaled default ({DEFAULT_SCALED_MAX_TURNS})"
                    )
                else:
                    new_max_turns = parsed_t
            except (ValueError, TypeError):
                data["max_turns"] = DEFAULT_SCALED_MAX_TURNS
                new_max_turns = DEFAULT_SCALED_MAX_TURNS

        # 3. Children and descendants defaults
        if "max_children_per_agent" not in data or data["max_children_per_agent"] in {3, 5}:
            data["max_children_per_agent"] = DEFAULT_MAX_CHILDREN_PER_AGENT

        if "max_descendants_per_run" not in data or data["max_descendants_per_run"] in {10, 20}:
            data["max_descendants_per_run"] = DEFAULT_MAX_DESCENDANTS_PER_RUN

        is_migrated = concurrency_migrated or max_turns_migrated
        result = ConfigMigrationResult(
            migrated=is_migrated,
            old_concurrency=old_concurrency,
            new_concurrency=new_concurrency,
            old_max_turns=old_max_turns,
            new_max_turns=new_max_turns,
            concurrency_migrated=concurrency_migrated,
            max_turns_migrated=max_turns_migrated,
            reasons=tuple(reasons),
        )

        return data, result
