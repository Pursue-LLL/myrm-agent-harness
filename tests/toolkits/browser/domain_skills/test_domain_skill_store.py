"""Tests for DomainSkillStore — manifest loading, domain matching, CRUD."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.browser.domain_skills import (
    DomainSkillManifest,
    DomainSkillStore,
    DomainTool,
)
from myrm_agent_harness.toolkits.browser.domain_skills.store import (
    _domain_matches,
    _normalize_hostname,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest_dir(base: Path, skill_id: str, domains: list[str]) -> Path:
    """Create a minimal manifest.json under base/skill_id/."""
    skill_dir = base / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    tools_dir = skill_dir / "tools"
    tools_dir.mkdir(exist_ok=True)

    script = tools_dir / "echo.py"
    script.write_text(
        "async def echo(session, args):\n    return 'ok'\n",
        encoding="utf-8",
    )

    manifest = {
        "id": skill_id,
        "name": f"Test {skill_id}",
        "domains": domains,
        "python_tools": {
            "echo": {
                "description": "Echo tool",
                "path": "tools/echo.py",
                "callable": "echo",
                "args": {"msg": {"type": "string", "required": "true"}},
                "returns": "echoed message",
            }
        },
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Unit: _domain_matches / _normalize_hostname
# ---------------------------------------------------------------------------

class TestDomainMatching:
    def test_exact_match(self) -> None:
        assert _domain_matches("x.com", "x.com") is True

    def test_exact_no_match(self) -> None:
        assert _domain_matches("y.com", "x.com") is False

    def test_wildcard_subdomain(self) -> None:
        assert _domain_matches("sub.x.com", "*.x.com") is True

    def test_wildcard_no_match_root(self) -> None:
        assert _domain_matches("x.com", "*.x.com") is False

    def test_case_insensitive(self) -> None:
        assert _domain_matches("x.com", "X.COM") is True

    def test_trailing_dot(self) -> None:
        assert _domain_matches("x.com", "x.com.") is True

    def test_normalize_www(self) -> None:
        assert _normalize_hostname("www.x.com") == "x.com"

    def test_normalize_plain(self) -> None:
        assert _normalize_hostname("x.com") == "x.com"

    def test_normalize_trailing_dot(self) -> None:
        assert _normalize_hostname("x.com.") == "x.com"

    def test_normalize_uppercase(self) -> None:
        assert _normalize_hostname("X.COM") == "x.com"


# ---------------------------------------------------------------------------
# Integration: DomainSkillStore
# ---------------------------------------------------------------------------

class TestDomainSkillStore:
    def test_load_builtin_x_com(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        skills = store.list_skills()
        ids = [s.id for s in skills]
        assert "x-com" in ids

    def test_match_x_com_url(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("https://x.com/home")
        assert len(matches) == 1
        assert matches[0].id == "x-com"

    def test_match_twitter_alias(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("https://twitter.com/user")
        assert len(matches) == 1

    def test_match_subdomain(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("https://mobile.x.com/explore")
        assert len(matches) == 1

    def test_no_match_other_domain(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("https://google.com/search")
        assert len(matches) == 0

    def test_no_match_empty_url(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.match("") == []

    def test_get_existing_skill(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        manifest = store.get("x-com")
        assert manifest is not None
        assert manifest.name == "X (Twitter)"

    def test_get_nonexistent_skill(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.get("nonexistent") is None

    def test_tool_script_path_resolves(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        path = store.get_tool_script_path("x-com", "get_timeline_posts")
        assert path is not None
        assert path.exists()
        assert path.name == "get_timeline_posts.py"

    def test_tool_script_path_nonexistent_tool(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.get_tool_script_path("x-com", "no_such_tool") is None

    def test_tool_script_path_nonexistent_skill(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.get_tool_script_path("no_skill", "echo") is None


class TestDomainSkillStoreUserDir:
    def test_load_user_directory(self, tmp_path: Path) -> None:
        _make_manifest_dir(tmp_path, "my-skill", ["example.com"])
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        skills = store.list_skills()
        assert len(skills) == 1
        assert skills[0].id == "my-skill"

    def test_user_dir_overrides_builtin(self, tmp_path: Path) -> None:
        _make_manifest_dir(tmp_path, "x-com", ["custom-x.com"])
        store = DomainSkillStore(load_builtin=True, user_dir=tmp_path)
        manifest = store.get("x-com")
        assert manifest is not None
        assert "custom-x.com" in manifest.domains

    def test_skips_underscore_dirs(self, tmp_path: Path) -> None:
        _make_manifest_dir(tmp_path, "_hidden", ["hidden.com"])
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        assert len(store.list_skills()) == 0

    def test_skips_dirs_without_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "no-manifest").mkdir()
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        assert len(store.list_skills()) == 0

    def test_malformed_manifest_skipped(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "manifest.json").write_text("NOT JSON", encoding="utf-8")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        assert len(store.list_skills()) == 0


class TestDomainSkillStoreCRUD:
    def test_add_user_skill(self, tmp_path: Path) -> None:
        store = DomainSkillStore(load_builtin=False, user_dir="/nonexistent")
        manifest = DomainSkillManifest(
            id="custom",
            name="Custom Skill",
            domains=("custom.io",),
            python_tools={},
        )
        store.add_user_skill(manifest, tmp_path)
        assert store.get("custom") is not None
        assert len(store.match("https://custom.io/page")) == 1

    def test_delete_skill(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.get("x-com") is not None
        removed = store.delete_skill("x-com")
        assert removed is True
        assert store.get("x-com") is None

    def test_delete_nonexistent(self) -> None:
        store = DomainSkillStore(load_builtin=False, user_dir="/nonexistent")
        assert store.delete_skill("nope") is False


class TestDomainSkillStoreEnvResolution:
    def test_myrm_data_dir_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path))
        resolved = DomainSkillStore._resolve_user_dir(None)
        assert resolved == tmp_path / "domain_skills"

    def test_explicit_path_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MYRM_DATA_DIR", "/should/not/use")
        resolved = DomainSkillStore._resolve_user_dir(tmp_path / "custom")
        assert resolved == tmp_path / "custom"


# ---------------------------------------------------------------------------
# DomainSkillManifest.tool_signatures
# ---------------------------------------------------------------------------

class TestToolSignatures:
    def test_empty_tools(self) -> None:
        m = DomainSkillManifest(id="t", name="T", domains=("t.com",))
        assert m.tool_signatures() == ""

    def test_single_tool_required_arg(self) -> None:
        tool = DomainTool(
            name="fetch",
            description="Fetch data",
            script_path="tools/fetch.py",
            callable_name="fetch",
            args={"url": {"type": "string", "required": "true"}},
        )
        m = DomainSkillManifest(
            id="t", name="T", domains=("t.com",),
            python_tools={"fetch": tool},
        )
        assert m.tool_signatures() == "fetch(url)"

    def test_optional_arg_has_question_mark(self) -> None:
        tool = DomainTool(
            name="search",
            description="Search",
            script_path="tools/search.py",
            callable_name="search",
            args={"query": {"type": "string", "required": "true"},
                  "limit": {"type": "integer", "required": "false"}},
        )
        m = DomainSkillManifest(
            id="t", name="T", domains=("t.com",),
            python_tools={"search": tool},
        )
        sig = m.tool_signatures()
        assert "query" in sig
        assert "limit?" in sig

    def test_multiple_tools_comma_separated(self) -> None:
        t1 = DomainTool(name="a", description="", script_path="", callable_name="a")
        t2 = DomainTool(name="b", description="", script_path="", callable_name="b")
        m = DomainSkillManifest(
            id="t", name="T", domains=("t.com",),
            python_tools={"a": t1, "b": t2},
        )
        sig = m.tool_signatures()
        assert "a()" in sig
        assert "b()" in sig
        assert ", " in sig


# ---------------------------------------------------------------------------
# URL extraction edge cases
# ---------------------------------------------------------------------------

class TestUrlExtraction:
    def test_url_without_scheme(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("x.com/home")
        assert len(matches) == 1

    def test_www_prefix_stripped(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        matches = store.match("https://www.x.com/home")
        assert len(matches) == 1

    def test_garbage_url(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.match("not a url at all %%%") == []


# ---------------------------------------------------------------------------
# is_builtin detection
# ---------------------------------------------------------------------------

class TestIsBuiltin:
    def test_builtin_skill_returns_true(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.is_builtin("x-com") is True

    def test_user_skill_returns_false(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "user_skills" / "my-skill"
        user_dir.mkdir(parents=True)
        (user_dir / "manifest.json").write_text(
            '{"id":"my-skill","name":"My","domains":["my.com"],"python_tools":{}}',
        )
        store = DomainSkillStore(load_builtin=True, user_dir=tmp_path / "user_skills")
        assert store.is_builtin("my-skill") is False

    def test_nonexistent_skill_returns_false(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        assert store.is_builtin("does-not-exist") is False


# ---------------------------------------------------------------------------
# Distill tool_name validation (Pydantic model_validator)
# ---------------------------------------------------------------------------

class TestDistillToolNameValidation:
    def test_valid_tool_name_accepted(self) -> None:
        import re
        pattern = re.compile(r"^[a-z0-9][a-z0-9_]*$")
        assert pattern.match("get_timeline_posts") is not None
        assert pattern.match("a") is not None
        assert pattern.match("x1_tool") is not None

    def test_path_traversal_rejected(self) -> None:
        import re
        pattern = re.compile(r"^[a-z0-9][a-z0-9_]*$")
        assert pattern.match("../../backdoor") is None
        assert pattern.match("../evil") is None

    def test_invalid_chars_rejected(self) -> None:
        import re
        pattern = re.compile(r"^[a-z0-9][a-z0-9_]*$")
        assert pattern.match("get-timeline") is None
        assert pattern.match("Get_Posts") is None
        assert pattern.match("_private") is None
        assert pattern.match("") is None


# ---------------------------------------------------------------------------
# Singleton: get_global_domain_skill_store
# ---------------------------------------------------------------------------

class TestGlobalSingleton:
    def test_returns_store_instance(self) -> None:
        import myrm_agent_harness.toolkits.browser.domain_skills.store as mod
        mod._global_store = None
        try:
            store = mod.get_global_domain_skill_store()
            assert isinstance(store, DomainSkillStore)
        finally:
            mod._global_store = None

    def test_returns_same_instance(self) -> None:
        import myrm_agent_harness.toolkits.browser.domain_skills.store as mod
        mod._global_store = None
        try:
            s1 = mod.get_global_domain_skill_store()
            s2 = mod.get_global_domain_skill_store()
            assert s1 is s2
        finally:
            mod._global_store = None


# ---------------------------------------------------------------------------
# _resolve_user_dir: /workspace/ fallback
# ---------------------------------------------------------------------------

class TestResolveUserDirWorkspace:
    def test_workspace_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_DATA_DIR", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/workspace/")
        resolved = DomainSkillStore._resolve_user_dir(None)
        assert resolved == Path("/workspace/.myrm/domain_skills")

    def test_home_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_DATA_DIR", raising=False)
        monkeypatch.setattr(os.path, "exists", lambda _p: False)
        resolved = DomainSkillStore._resolve_user_dir(None)
        assert resolved == Path.home() / ".myrm" / "domain_skills"


# ---------------------------------------------------------------------------
# _load_directory: non-directory path
# ---------------------------------------------------------------------------

class TestLoadDirectoryEdge:
    def test_load_nondir_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        store = DomainSkillStore(load_builtin=False, user_dir="/nonexistent")
        store._load_directory(f)
        assert store.list_skills() == []

    def test_files_in_dir_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# readme")
        (tmp_path / ".hidden").write_text("x")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        assert store.list_skills() == []


# ---------------------------------------------------------------------------
# _parse_manifest: default value fallback
# ---------------------------------------------------------------------------

class TestParseManifestDefaults:
    def test_id_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-dir-name"
        skill_dir.mkdir()
        manifest = {"name": "Test", "domains": ["t.com"], "python_tools": {}}
        (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        assert store.get("my-dir-name") is not None

    def test_name_falls_back_to_id(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "auto-name"
        skill_dir.mkdir()
        manifest = {"id": "auto-name", "domains": ["a.com"], "python_tools": {}}
        (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        m = store.get("auto-name")
        assert m is not None
        assert m.name == "auto-name"

    def test_missing_tools_key(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-tools"
        skill_dir.mkdir()
        manifest = {"id": "no-tools", "name": "No Tools", "domains": ["n.com"]}
        (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        m = store.get("no-tools")
        assert m is not None
        assert m.python_tools == {}

    def test_tool_callable_falls_back_to_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "cb-fallback"
        skill_dir.mkdir()
        manifest = {
            "id": "cb-fallback",
            "name": "CB",
            "domains": ["cb.com"],
            "python_tools": {
                "my_tool": {"description": "d", "path": "tools/my_tool.py"},
            },
        }
        (skill_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        m = store.get("cb-fallback")
        assert m is not None
        assert m.python_tools["my_tool"].callable_name == "my_tool"


# ---------------------------------------------------------------------------
# Multi-skill matching & add_user_skill override
# ---------------------------------------------------------------------------

class TestMultiSkillMatching:
    def test_multiple_skills_match_same_domain(self, tmp_path: Path) -> None:
        _make_manifest_dir(tmp_path, "skill-a", ["shared.com"])
        _make_manifest_dir(tmp_path, "skill-b", ["shared.com"])
        store = DomainSkillStore(load_builtin=False, user_dir=tmp_path)
        matches = store.match("https://shared.com/page")
        assert len(matches) == 2
        ids = {m.id for m in matches}
        assert ids == {"skill-a", "skill-b"}


class TestAddUserSkillOverride:
    def test_add_overrides_existing(self) -> None:
        store = DomainSkillStore(load_builtin=True, user_dir="/nonexistent")
        original = store.get("x-com")
        assert original is not None
        override = DomainSkillManifest(
            id="x-com",
            name="Overridden X",
            domains=("custom-x.com",),
        )
        store.add_user_skill(override, Path("/tmp/override"))
        updated = store.get("x-com")
        assert updated is not None
        assert updated.name == "Overridden X"
        assert "custom-x.com" in updated.domains
