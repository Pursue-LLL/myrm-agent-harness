"""Unit tests for lockfile dependency extraction (uv.lock, bun.lock, package-lock.json)."""

from __future__ import annotations

import json

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import (
    extract_dependencies_from_bun_lock,
    extract_dependencies_from_files,
    extract_dependencies_from_package_lock_json,
    extract_dependencies_from_uv_lock,
)


def test_extract_dependencies_from_uv_lock_basic() -> None:
    content = """
version = 1
revision = 1

[[package]]
name = "aiofiles"
version = "25.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "fastapi"
version = "0.115.0"
dependencies = [
    { name = "pydantic" },
]
"""
    deps = extract_dependencies_from_uv_lock(content, "uv.lock")
    assert len(deps) == 2
    assert deps[0].name == "aiofiles"
    assert deps[0].version_spec == "25.1.0"
    assert deps[0].ecosystem == "PyPI"
    assert deps[0].file_path == "uv.lock"

    assert deps[1].name == "fastapi"
    assert deps[1].version_spec == "0.115.0"
    assert deps[1].ecosystem == "PyPI"


def test_extract_dependencies_from_bun_lock_workspaces() -> None:
    data = {
        "lockfileVersion": 1,
        "workspaces": {
            "": {
                "name": "root",
                "dependencies": {
                    "react": "^19.0.0",
                    "next": "15.1.0",
                },
                "devDependencies": {
                    "typescript": "^5.0.0",
                },
            }
        },
    }
    content = json.dumps(data)
    deps = extract_dependencies_from_bun_lock(content, "bun.lock")
    assert len(deps) == 3

    names = {d.name: (d.version_spec, d.is_dev) for d in deps}
    assert "react" in names
    assert names["react"] == ("^19.0.0", False)
    assert "next" in names
    assert names["next"] == ("15.1.0", False)
    assert "typescript" in names
    assert names["typescript"] == ("^5.0.0", True)


def test_extract_dependencies_from_package_lock_json_v3() -> None:
    data = {
        "name": "test-pkg",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "test-pkg",
            },
            "node_modules/express": {
                "version": "4.19.2",
                "dev": False,
            },
            "node_modules/@types/node": {
                "name": "@types/node",
                "version": "20.11.0",
                "dev": True,
            },
        },
    }
    content = json.dumps(data)
    deps = extract_dependencies_from_package_lock_json(content, "package-lock.json")
    assert len(deps) == 2

    dep_map = {d.name: (d.version_spec, d.is_dev) for d in deps}
    assert "express" in dep_map
    assert dep_map["express"] == ("4.19.2", False)
    assert "@types/node" in dep_map
    assert dep_map["@types/node"] == ("20.11.0", True)


def test_extract_dependencies_from_files_lockfiles() -> None:
    uv_content = b"""
[[package]]
name = "pydantic"
version = "2.9.2"
"""

    files = {
        "workspace/uv.lock": uv_content,
    }

    deps = extract_dependencies_from_files(files)
    assert len(deps) == 1
    assert deps[0].name == "pydantic"
    assert deps[0].version_spec == "2.9.2"
    assert deps[0].ecosystem == "PyPI"
