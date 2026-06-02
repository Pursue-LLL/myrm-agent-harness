#!/usr/bin/env python3
"""Generate harness_release_manifest.json with SHA256 checksums for release wheels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


_PLATFORM_RE = re.compile(r"^myrm_agent_harness_core_([a-z0-9_]+)-", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_key(filename: str) -> str:
    match = _PLATFORM_RE.match(filename)
    if match is None:
        return "all"
    return match.group(1).replace("_", "-")


def generate_manifest(tag: str, assets_dir: Path) -> dict[str, object]:
    wheels: dict[str, dict[str, str]] = {}
    for path in sorted(assets_dir.glob("*.whl")):
        wheels[path.name] = {
            "sha256": _sha256(path),
            "platform": _platform_key(path.name),
        }
    if not wheels:
        raise SystemExit(f"No .whl files found under {assets_dir}")
    return {"tag": tag, "wheels": wheels}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets_dir", type=Path, help="Directory containing release .whl files")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v0.1.0-rc1")
    parser.add_argument(
        "--output",
        type=Path,
        help="Manifest output path (default: assets_dir/harness_release_manifest.json)",
    )
    args = parser.parse_args(argv or sys.argv[1:])
    manifest = generate_manifest(args.tag, args.assets_dir)
    output = args.output or (args.assets_dir / "harness_release_manifest.json")
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
