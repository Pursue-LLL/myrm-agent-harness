"""Context bundle migration and dry-run utilities.

[INPUT]
- .spec::CONTEXT_BUNDLE_SCHEMA_VERSION, ContextBundleSpec (POS: context bundle specification)
- .volume::VolumeLayout, BUNDLE_MANIFEST_FILENAME (POS: context bundle volume layout)

[OUTPUT]
- MigrationAction: planned migration step
- MigrationReport: dry-run or apply result summary
- run_migration_dry_run: non-destructive layout validation

[POS]
Validates and initializes bundle manifest/layout without mutating user memory content.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .spec import ContextBundleSpec
from .volume import BUNDLE_MANIFEST_FILENAME, VolumeLayout


@dataclass(frozen=True, slots=True)
class MigrationAction:
    """Single migration step surfaced to Server/API."""

    id: str
    description: str
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Dry-run or apply report for a context bundle."""

    bundle_id: str
    schema_version: int
    volume_layout_version: int
    state_dir: str
    writable: bool
    manifest_exists: bool
    actions: tuple[MigrationAction, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.writable and not any(action.destructive for action in self.actions)


def _is_writable(path: Path) -> bool:
    target = path if path.exists() else path.parent
    return target.exists() and os.access(target, os.W_OK)


def run_migration_dry_run(
    state_dir: str | Path,
    *,
    spec: ContextBundleSpec | None = None,
) -> MigrationReport:
    """Validate bundle layout and manifest without destructive changes."""
    bundle_spec = spec or ContextBundleSpec()
    layout = VolumeLayout.from_state_dir(state_dir)
    actions: list[MigrationAction] = []
    warnings: list[str] = []

    manifest = VolumeLayout.read_manifest(state_dir)
    manifest_exists = manifest is not None

    if not _is_writable(layout.state_dir):
        warnings.append(f"State directory is not writable: {layout.state_dir}")

    for label, path in (
        ("memory", layout.memory_path),
        ("harness", layout.harness_path),
        ("offload", layout.offload_root),
        ("archive", layout.archive_path),
    ):
        if not path.exists():
            actions.append(
                MigrationAction(
                    id=f"create_{label}_dir",
                    description=f"Create missing {label} directory at {path}",
                    destructive=False,
                )
            )

    if not manifest_exists:
        actions.append(
            MigrationAction(
                id="write_manifest",
                description=f"Write {BUNDLE_MANIFEST_FILENAME} at bundle root",
                destructive=False,
            )
        )
    elif manifest is not None:
        existing_version = manifest.get("schema_version")
        if existing_version != bundle_spec.schema_version:
            warnings.append(
                f"Manifest schema_version={existing_version!r} differs from expected {bundle_spec.schema_version}"
            )

    return MigrationReport(
        bundle_id=bundle_spec.bundle_id,
        schema_version=bundle_spec.schema_version,
        volume_layout_version=bundle_spec.volume_layout_version,
        state_dir=str(layout.state_dir),
        writable=_is_writable(layout.state_dir),
        manifest_exists=manifest_exists,
        actions=tuple(actions),
        warnings=tuple(warnings),
    )


def apply_migration(
    state_dir: str | Path,
    *,
    spec: ContextBundleSpec | None = None,
) -> MigrationReport:
    """Apply non-destructive migration steps (mkdir + manifest write)."""
    report = run_migration_dry_run(state_dir, spec=spec)
    if not report.writable:
        return report

    bundle_spec = spec or ContextBundleSpec()
    layout = VolumeLayout.from_state_dir(state_dir)
    layout.ensure_directories()
    layout.write_manifest(
        bundle_id=bundle_spec.bundle_id,
        schema_version=bundle_spec.schema_version,
    )
    return run_migration_dry_run(state_dir, spec=spec)
