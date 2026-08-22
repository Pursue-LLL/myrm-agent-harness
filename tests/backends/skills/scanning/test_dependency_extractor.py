"""Tests for dependency_extractor.py — package.json, requirements.txt, pyproject.toml."""

from pathlib import Path

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import (
    DeclaredDependency,
    extract_dependencies_from_files,
    extract_dependencies_from_package_json,
    extract_dependencies_from_pyproject_toml,
    extract_dependencies_from_requirements_txt,
    extract_skill_dependencies,
)


def test_extract_dependencies_from_package_json() -> None:
    pkg_json = """{
        "name": "my-skill",
        "dependencies": {
            "axios": "^1.2.0",
            "lodash": "4.17.21"
        },
        "devDependencies": {
            "typescript": "^5.0.0"
        },
        "peerDependencies": {
            "react": ">=18.0.0"
        }
    }"""
    deps = extract_dependencies_from_package_json(pkg_json, "package.json")
    assert len(deps) == 4
    names = {d.name: (d.version_spec, d.is_dev) for d in deps}
    assert "axios" in names
    assert names["axios"] == ("^1.2.0", False)
    assert "typescript" in names
    assert names["typescript"] == ("^5.0.0", True)
    assert "react" in names
    assert names["react"] == (">=18.0.0", False)


def test_extract_dependencies_from_package_json_invalid() -> None:
    assert extract_dependencies_from_package_json("invalid json") == []
    assert extract_dependencies_from_package_json("[]") == []


def test_extract_dependencies_from_requirements_txt() -> None:
    req_txt = """# Requirements
requests==2.28.1
urllib3>=1.26.0,<2.0.0; python_version >= '3.8'
pydantic[email]>=2.0.0 # with extras
-r base.txt
--index-url https://pypi.org/simple
"""
    deps = extract_dependencies_from_requirements_txt(req_txt, "requirements.txt")
    assert len(deps) == 3
    names = {d.name: d.version_spec for d in deps}
    assert names["requests"] == "==2.28.1"
    assert names["urllib3"] == ">=1.26.0,<2.0.0"
    assert names["pydantic"] == ">=2.0.0"


def test_extract_dependencies_from_pyproject_toml() -> None:
    toml_str = """
    [project]
    name = "skill-py"
    dependencies = [
        "httpx>=0.24.0",
        "fastapi==0.100.0",
    ]

    [project.optional-dependencies]
    test = [
        "pytest>=7.0.0",
    ]

    [tool.poetry.dependencies]
    python = "^3.11"
    jinja2 = "^3.1.2"
    """
    deps = extract_dependencies_from_pyproject_toml(toml_str, "pyproject.toml")
    assert len(deps) == 4
    names = {d.name: (d.version_spec, d.is_dev) for d in deps}
    assert names["httpx"] == (">=0.24.0", False)
    assert names["fastapi"] == ("==0.100.0", False)
    assert names["pytest"] == (">=7.0.0", True)
    assert names["jinja2"] == ("^3.1.2", False)


def test_extract_dependencies_from_files() -> None:
    files = {
        "package.json": b'{"dependencies": {"express": "^4.18.0"}}',
        "requirements.txt": b"cryptography==41.0.0\n",
    }
    deps = extract_dependencies_from_files(files)
    assert len(deps) == 2
    eco_map = {d.name: d.ecosystem for d in deps}
    assert eco_map["express"] == "npm"
    assert eco_map["cryptography"] == "PyPI"


def test_extract_skill_dependencies_on_disk(tmp_path: Path) -> None:
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "package.json").write_text('{"dependencies": {"debug": "4.3.4"}}', encoding="utf-8")
    (skill_dir / "requirements.txt").write_text("numpy==1.24.0\n", encoding="utf-8")

    deps = extract_skill_dependencies(skill_dir)
    assert len(deps) == 2
    assert {d.name for d in deps} == {"debug", "numpy"}

def test_extract_dependencies_from_pyproject_toml_invalid() -> None:
    assert extract_dependencies_from_pyproject_toml("invalid toml [") == []
    assert extract_dependencies_from_pyproject_toml("") == []


def test_extract_skill_dependencies_depth_and_errors(tmp_path: Path) -> None:
    skill_dir = tmp_path / "deep-skill"
    skill_dir.mkdir()
    d1 = skill_dir / "d1"
    d1.mkdir()
    d2 = d1 / "d2"
    d2.mkdir()
    d3 = d2 / "d3"
    d3.mkdir()
    d4 = d3 / "d4"
    d4.mkdir()
    (d4 / "package.json").write_text('{"dependencies": {"deep": "1.0.0"}}', encoding="utf-8")

    # Depth > 3 is skipped
    deps = extract_skill_dependencies(skill_dir)
    assert not any(d.name == "deep" for d in deps)
