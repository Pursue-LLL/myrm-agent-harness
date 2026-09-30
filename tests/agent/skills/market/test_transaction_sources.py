"""Unit tests for the skill install transaction, receipts, and misc sources.

[INPUT]
- myrm_agent_harness.agent.skills.market.transaction
- myrm_agent_harness.agent.skills.market.sources.prebuilt
- myrm_agent_harness.agent.skills.market.sources.skills_sh
- myrm_agent_harness.agent.skills.market.sources.lobehub

[OUTPUT]
- pytest suite covering snapshot rollback, receipt round-trips, and the
  prebuilt, skills.sh (with GitHub fallback), and LobeHub source paths.
  All HTTP is stubbed.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_transaction_sources.py
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.sources.lobehub import LobeHubSource
from myrm_agent_harness.agent.skills.market.sources.prebuilt import (
    PrebuiltSkillSource,
    _compute_match_score,
)
from myrm_agent_harness.agent.skills.market.sources.skills_sh import SkillsShSource
from myrm_agent_harness.agent.skills.market.transaction import (
    RECEIPT_FILENAME,
    SkillInstallTransaction,
    build_skill_receipt,
    compute_files_digest,
    read_receipt_file,
    write_receipt_file,
)

FILES = {"SKILL.md": b"# a\n", "data/x.txt": b"payload"}


def _make_dir(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_bytes(content)
    return path


class TestDigests:
    def test_digest_is_order_independent(self) -> None:
        first, hash_a = compute_files_digest({"b.txt": b"b", "a.txt": b"a"})
        second, hash_b = compute_files_digest({"a.txt": b"a", "b.txt": b"b"})
        assert [d.relative_path for d in first] == ["a.txt", "b.txt"]
        assert first == second
        assert hash_a == hash_b

    def test_digest_records_size(self) -> None:
        digests, _ = compute_files_digest({"a.txt": b"12345"})
        assert digests[0].size_bytes == 5

    def test_digest_changes_with_content(self) -> None:
        _, hash_a = compute_files_digest({"a.txt": b"a"})
        _, hash_b = compute_files_digest({"a.txt": b"b"})
        assert hash_a != hash_b


class TestReceipts:
    def test_receipt_round_trip(self, tmp_path: Path) -> None:
        receipt = build_skill_receipt(
            skill_id="id",
            skill_name="pdf",
            source="github",
            installed_path=str(tmp_path),
            files=FILES,
            version="1.0.0",
            installed_skills=["pdf", "extract"],
            declared_mcp_servers=["fs"],
        )
        write_receipt_file(tmp_path, receipt)

        loaded = read_receipt_file(tmp_path)

        assert loaded is not None
        assert loaded.skill_id == "id"
        assert loaded.installed_skills == ("pdf", "extract")
        assert loaded.declared_mcp_servers == ("fs",)
        assert {d.relative_path for d in loaded.files} == {"SKILL.md", "data/x.txt"}

    def test_receipt_written_to_expected_filename(self, tmp_path: Path) -> None:
        receipt = build_skill_receipt(
            skill_id="id", skill_name="pdf", source="s", installed_path=str(tmp_path), files=FILES
        )
        write_receipt_file(tmp_path, receipt)
        assert (tmp_path / RECEIPT_FILENAME).exists()

    def test_receipt_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.write_text("file", encoding="utf-8")
        receipt = build_skill_receipt(
            skill_id="id", skill_name="pdf", source="s", installed_path=str(blocked), files=FILES
        )
        write_receipt_file(blocked, receipt)

    def test_missing_receipt_returns_none(self, tmp_path: Path) -> None:
        assert read_receipt_file(tmp_path) is None

    def test_corrupt_receipt_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / RECEIPT_FILENAME).write_text("{not json", encoding="utf-8")
        assert read_receipt_file(tmp_path) is None

    def test_receipt_with_bad_file_entry_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / RECEIPT_FILENAME).write_text(
            json.dumps({"files": [{"relative_path": "a", "sha256": "x"}]}), encoding="utf-8"
        )
        assert read_receipt_file(tmp_path) is None

    def test_receipt_defaults(self, tmp_path: Path) -> None:
        (tmp_path / RECEIPT_FILENAME).write_text(json.dumps({"skill_id": "x"}), encoding="utf-8")
        loaded = read_receipt_file(tmp_path)
        assert loaded is not None
        assert loaded.scan_score == 100
        assert loaded.security_verified is True
        assert loaded.installed_path == str(tmp_path)


class TestTransaction:
    def test_stage_creates_new_target(self, tmp_path: Path) -> None:
        source = _make_dir(tmp_path / "src", "s", b"new")
        target = tmp_path / "dst" / "skill"

        with SkillInstallTransaction() as tx:
            tx.stage_replace(source, target)

        assert (target / "SKILL.md").read_bytes() == b"new"

    def test_commit_clears_state(self, tmp_path: Path) -> None:
        source = _make_dir(tmp_path / "src", "s")
        target = tmp_path / "skill"
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)

        tx.commit()

        assert tx._staged_targets == []
        assert tx._created_dirs == []

    def test_rollback_restores_snapshot(self, tmp_path: Path) -> None:
        target = _make_dir(tmp_path / "dst", "skill", b"old")
        source = _make_dir(tmp_path / "src", "s", b"new")
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)

        tx.rollback()

        assert (target / "SKILL.md").read_bytes() == b"old"

    def test_rollback_removes_created_dirs(self, tmp_path: Path) -> None:
        source = _make_dir(tmp_path / "src", "s")
        target = tmp_path / "skill"
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)

        tx.rollback()

        assert not target.exists()

    def test_rollback_after_commit_is_noop(self, tmp_path: Path) -> None:
        target = _make_dir(tmp_path / "dst", "skill", b"old")
        source = _make_dir(tmp_path / "src", "s", b"new")
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)
        tx.commit()

        tx.rollback()

        assert (target / "SKILL.md").read_bytes() == b"new"

    def test_context_manager_rolls_back_on_error(self, tmp_path: Path) -> None:
        target = _make_dir(tmp_path / "dst", "skill", b"old")
        source = _make_dir(tmp_path / "src", "s", b"new")

        with pytest.raises(RuntimeError, match="boom"), SkillInstallTransaction() as tx:
            tx.stage_replace(source, target)
            raise RuntimeError("boom")

        assert (target / "SKILL.md").read_bytes() == b"old"

    def test_context_manager_commits_on_success(self, tmp_path: Path) -> None:
        source = _make_dir(tmp_path / "src", "s", b"new")
        target = tmp_path / "skill"

        with SkillInstallTransaction() as tx:
            tx.stage_replace(source, target)

        assert (target / "SKILL.md").read_bytes() == b"new"

    def test_stage_resolves_symlink_to_its_target(self, tmp_path: Path) -> None:
        """stage_replace 先 resolve()，因此符号链接目标才是实际写入位置。"""
        source = _make_dir(tmp_path / "src", "s", b"new")
        real = _make_dir(tmp_path / "real", "skill", b"old")
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)

        SkillInstallTransaction().stage_replace(source, link)

        assert (real / "SKILL.md").read_bytes() == b"new"

    def test_rollback_skips_already_removed_created_dirs(self, tmp_path: Path) -> None:
        import shutil

        source = _make_dir(tmp_path / "src", "s")
        target = tmp_path / "skill"
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)
        shutil.rmtree(target)

        tx.rollback()

        assert not target.exists()

    def test_rollback_survives_restore_failure(self, tmp_path: Path) -> None:
        target = _make_dir(tmp_path / "dst", "skill", b"old")
        source = _make_dir(tmp_path / "src", "s", b"new")
        tx = SkillInstallTransaction()
        tx.stage_replace(source, target)

        with patch(
            "myrm_agent_harness.agent.skills.market.transaction.shutil.copytree",
            side_effect=OSError("cannot restore"),
        ):
            tx.rollback()

        assert tx._staged_targets == []


def _skill(skill_id: str = "a", name: str = "Alpha", **kwargs: object) -> SimpleNamespace:
    payload: dict[str, object] = {
        "id": skill_id,
        "name": name,
        "description": "does alpha",
        "version": "1.0.0",
        "tags": ["pdf"],
    }
    payload.update(kwargs)
    return SimpleNamespace(**payload)


class TestPrebuiltSource:
    @pytest.mark.asyncio
    async def test_blank_query_returns_all(self) -> None:
        store = SimpleNamespace(list_installed=AsyncMock(return_value=[_skill(), _skill("b", "Beta")]))
        results = await PrebuiltSkillSource(store).search("")
        assert [r.id for r in results] == ["a", "b"]
        assert results[0].source == "prebuilt"
        assert results[0].install_method == "direct"

    @pytest.mark.asyncio
    async def test_filters_by_keyword(self) -> None:
        store = SimpleNamespace(list_installed=AsyncMock(return_value=[_skill(), _skill("b", "Beta")]))
        results = await PrebuiltSkillSource(store).search("beta")
        assert [r.id for r in results] == ["b"]

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        store = SimpleNamespace(list_installed=AsyncMock(return_value=[_skill(), _skill("b", "Beta")]))
        assert len(await PrebuiltSkillSource(store).search("", limit=1)) == 1

    @pytest.mark.asyncio
    async def test_listing_failure_returns_empty(self) -> None:
        store = SimpleNamespace(list_installed=AsyncMock(side_effect=RuntimeError("store down")))
        assert await PrebuiltSkillSource(store).search("a") == []

    @pytest.mark.asyncio
    async def test_get_detail_finds_and_misses(self) -> None:
        store = SimpleNamespace(get_installed=AsyncMock(return_value=_skill()))
        source = PrebuiltSkillSource(store)
        assert (await source.get_detail("a")).id == "a"

        store.get_installed = AsyncMock(return_value=None)
        assert await source.get_detail("absent") is None

    def test_source_name(self) -> None:
        store = SimpleNamespace()
        assert PrebuiltSkillSource(store).source_name == "prebuilt"

    def test_score_prefers_name_then_tags_then_description(self) -> None:
        assert _compute_match_score("alpha", "d", [], ["alpha"]) == 10
        assert _compute_match_score("n", "d", ["alpha"], ["alpha"]) == 5
        assert _compute_match_score("n", "alpha here", [], ["alpha"]) == 2
        assert _compute_match_score("n", "d", [], ["zzz"]) == 0

    def test_score_is_case_insensitive(self) -> None:
        assert _compute_match_score("Alpha", "", [], ["ALPHA"]) == 10
        assert _compute_match_score("n", "", ["ALPHA"], ["Alpha"]) == 5


def _stub_client(status: int = 200, payload: object = None) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestSkillsShSource:
    def test_source_name(self) -> None:
        assert SkillsShSource().source_name == "skills_sh"

    @pytest.mark.asyncio
    async def test_search_parses_results(self) -> None:
        client = _stub_client(payload={"results": [{"id": "a", "name": "Alpha"}]})
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            results = await SkillsShSource().search("alpha")
        assert [r.id for r in results] == ["a"]

    @pytest.mark.asyncio
    async def test_search_falls_back_to_github(self) -> None:
        client = _stub_client(
            payload={"items": [{"full_name": "acme/tools", "name": "tools", "clone_url": "u", "topics": ["x"]}]}
        )
        client.get = AsyncMock(
            side_effect=[
                MagicMock(status_code=500, json=MagicMock()),
                MagicMock(
                    status_code=200,
                    json=MagicMock(
                        return_value={
                            "items": [
                                {
                                    "full_name": "acme/tools",
                                    "name": "tools",
                                    "clone_url": "u",
                                    "topics": ["x"],
                                    "stargazers_count": 4,
                                },
                                "junk",
                            ]
                        }
                    ),
                ),
            ]
        )
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            results = await SkillsShSource().search("alpha")

        assert [r.id for r in results] == ["acme/tools"]
        assert results[0].author == "acme"
        assert results[0].install_method == "git"

    @pytest.mark.asyncio
    async def test_fallback_non_200_returns_empty(self) -> None:
        client = _stub_client(status=500)
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert await SkillsShSource().search("alpha") == []

    @pytest.mark.asyncio
    async def test_fallback_bad_items_returns_empty(self) -> None:
        client = _stub_client()
        client.get = AsyncMock(
            side_effect=[
                MagicMock(status_code=500, json=MagicMock()),
                MagicMock(status_code=200, json=MagicMock(return_value={"items": "nope"})),
            ]
        )
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert await SkillsShSource().search("alpha") == []

    @pytest.mark.asyncio
    async def test_fallback_error_returns_empty(self) -> None:
        client = _stub_client(status=500)
        client.get = AsyncMock(
            side_effect=[
                MagicMock(status_code=500, json=MagicMock()),
                RuntimeError("github down"),
            ]
        )
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert await SkillsShSource().search("alpha") == []

    @pytest.mark.asyncio
    async def test_search_timeout_returns_empty(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            side_effect=httpx.TimeoutException("slow"),
        ):
            assert await SkillsShSource().search("alpha") == []

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            side_effect=RuntimeError("boom"),
        ):
            assert await SkillsShSource().search("alpha") == []

    @pytest.mark.asyncio
    async def test_get_detail_parses(self) -> None:
        client = _stub_client(payload={"id": "a", "name": "Alpha"})
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert (await SkillsShSource().get_detail("a")).id == "a"

    @pytest.mark.asyncio
    async def test_get_detail_rejects_non_dict(self) -> None:
        client = _stub_client(payload=["not", "dict"])
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert await SkillsShSource().get_detail("a") is None

    @pytest.mark.asyncio
    async def test_get_detail_non_200_returns_none(self) -> None:
        client = _stub_client(status=404)
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            return_value=client,
        ):
            assert await SkillsShSource().get_detail("a") is None

    @pytest.mark.asyncio
    async def test_get_detail_error_returns_none(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.skills_sh.create_httpx_client",
            side_effect=RuntimeError("boom"),
        ):
            assert await SkillsShSource().get_detail("a") is None

    def test_parse_rejects_scalar_payload(self) -> None:
        assert SkillsShSource()._parse_search_results("scalar") == []

    def test_parse_accepts_skills_and_items_keys(self) -> None:
        source = SkillsShSource()
        assert source._parse_search_results({"skills": [{"id": "a"}]})
        assert source._parse_search_results({"items": [{"id": "b"}]})

    @pytest.mark.asyncio
    @respx.mock
    async def test_item_to_result_maps_fields(self) -> None:
        result = SkillsShSource()._item_to_result(
            {"id": "a", "name": "Alpha", "description": "d", "stars": 3, "tags": ["t"]}
        )
        assert result.id == "a"
        assert result.stars == 3
        assert result.tags == ["t"]
        assert respx is not None


class TestSkillsShInstallTarget:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"source": "acme/tools"}, ("https://github.com/acme/tools.git", "alpha")),
            ({}, ("https://github.com/acme/tools.git", "alpha")),
            ({"source": "acme/tools", "skillId": "extract"}, ("https://github.com/acme/tools.git", "extract")),
            ({"name": "alpha"}, ("https://github.com/acme/tools.git", "alpha")),
        ],
    )
    def test_clone_url_and_subdirectory(self, payload: dict[str, object], expected: tuple[str, str]) -> None:
        assert SkillsShSource()._derive_github_url("acme/tools/alpha", payload) == expected

    def test_rejects_short_id_without_source(self) -> None:
        assert SkillsShSource()._derive_github_url("solo", {}) == ("", None)

    def test_skill_name_requires_three_segments(self) -> None:
        # 不足三段时无技能名，subdirectory 回落为 None
        assert SkillsShSource()._derive_github_url("acme/tools", {}) == (
            "https://github.com/acme/tools.git",
            None,
        )

    def test_item_author_falls_back_to_source_prefix(self) -> None:
        result = SkillsShSource()._item_to_result({"id": "acme/tools/alpha", "source": "acme/tools"})
        assert result.author == "acme"

    def test_parse_rejects_bad_nested_field(self) -> None:
        assert SkillsShSource()._parse_search_results({"results": "nope"}) == []

    def test_parse_accepts_bare_list(self) -> None:
        assert [r.id for r in SkillsShSource()._parse_search_results([{"id": "a"}])] == ["a"]


class TestLobeHubSource:
    @pytest.mark.asyncio
    async def test_search_returns_empty_without_network(self) -> None:
        assert LobeHubSource is not None
        with respx.mock:
            respx.get(url__startswith="https://lobehub.com").mock(return_value=httpx.Response(404))
            assert await LobeHubSource().search("alpha") == []
