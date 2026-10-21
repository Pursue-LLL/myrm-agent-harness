"""CompositeSkillBackend must serve the content of every skill it lists.

`list_skills()` yields bare names and `storage_skill_id`s; callers (`get_skill_document`, skill hooks,
the SOP preload) hand those straight back to `get_skill_content` / `get_skill_resources`. Route prefixes
never appear in them, so ownership has to be resolved, not prefix-matched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills import CompositeSkillBackend, LocalSkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata


class _StubBackend:
    """Backend owning a fixed set of skills; records every key it is asked for."""

    def __init__(self, label: str, owned: dict[str, list[str]] | None = None) -> None:
        self.label = label
        self.owned = owned or {}
        self.asked: list[str] = []

    async def list_skills(self) -> list[SkillMetadata]:
        return [SkillMetadata(name=name, description=self.label) for name in self.owned]

    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        return [skill for skill in await self.list_skills() if skill.name in skill_ids]

    async def get_skill_content(self, skill_name: str) -> str:
        self.asked.append(skill_name)
        if skill_name not in self.owned:
            raise FileNotFoundError(skill_name)
        return f"{self.label}:{skill_name}"

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        self.asked.append(skill_name)
        if skill_name not in self.owned or path not in self.owned[skill_name]:
            raise FileNotFoundError(f"{skill_name}/{path}")
        return f"{self.label}:{skill_name}/{path}".encode()

    async def list_skill_resources(self, skill_name: str) -> list[str]:
        self.asked.append(skill_name)
        return list(self.owned.get(skill_name, []))


class TestFlatKeyResolution:
    @pytest.mark.asyncio
    async def test_bare_name_reaches_the_route_that_owns_it(self) -> None:
        user = _StubBackend("user", {"mine": []})
        prebuilt = _StubBackend("prebuilt", {"pdf": []})
        composite = CompositeSkillBackend(routes={"/user/": user}, default=prebuilt)

        assert await composite.get_skill_content("mine") == "user:mine"
        assert await composite.get_skill_content("pdf") == "prebuilt:pdf"

    @pytest.mark.asyncio
    async def test_routes_without_a_default_still_serve_what_they_list(self) -> None:
        composite = CompositeSkillBackend(
            routes={"/prebuilt/": _StubBackend("prebuilt", {"pdf": []}), "/user/": _StubBackend("user", {"mine": []})},
        )

        listed = {skill.name for skill in await composite.list_skills()}
        assert listed == {"pdf", "mine"}
        for name in listed:
            assert (await composite.get_skill_content(name)).endswith(f":{name}")

    @pytest.mark.asyncio
    async def test_duplicate_name_is_served_by_the_backend_list_skills_keeps(self) -> None:
        """Later route wins in list_skills; its content must be the one served."""
        default = _StubBackend("default", {"shared": []})
        early = _StubBackend("early", {"shared": []})
        late = _StubBackend("late", {"shared": []})
        composite = CompositeSkillBackend(routes={"/early/": early, "/late/": late}, default=default)

        listed = {skill.name: skill.description for skill in await composite.list_skills()}
        assert listed["shared"] == "late"
        assert await composite.get_skill_content("shared") == "late:shared"

    @pytest.mark.asyncio
    async def test_unknown_skill_raises_file_not_found(self) -> None:
        composite = CompositeSkillBackend(routes={"/user/": _StubBackend("user", {"mine": []})})

        with pytest.raises(FileNotFoundError):
            await composite.get_skill_content("ghost")

    @pytest.mark.asyncio
    async def test_composite_without_any_backend_is_a_configuration_error(self) -> None:
        composite = CompositeSkillBackend(routes={})

        with pytest.raises(ValueError, match="No backend found"):
            await composite.get_skill_content("anything")


class TestPrefixedKeys:
    @pytest.mark.asyncio
    async def test_prefixed_key_is_sent_to_that_route_only(self) -> None:
        user = _StubBackend("user", {"/user/mine": []})
        other = _StubBackend("other", {"/user/mine": []})
        composite = CompositeSkillBackend(routes={"/user/": user}, default=other)

        assert await composite.get_skill_content("/user/mine") == "user:/user/mine"
        assert other.asked == []

    @pytest.mark.asyncio
    async def test_prefixed_key_missing_in_its_route_does_not_fall_through(self) -> None:
        user = _StubBackend("user", {})
        other = _StubBackend("other", {"/user/mine": []})
        composite = CompositeSkillBackend(routes={"/user/": user}, default=other)

        with pytest.raises(FileNotFoundError):
            await composite.get_skill_content("/user/mine")
        assert other.asked == []


class TestResources:
    @pytest.mark.asyncio
    async def test_resource_comes_from_the_owning_backend(self) -> None:
        user = _StubBackend("user", {"mine": ["scripts/run.py"]})
        composite = CompositeSkillBackend(routes={"/user/": user}, default=_StubBackend("default"))

        assert await composite.get_skill_resources("mine", "scripts/run.py") == b"user:mine/scripts/run.py"
        assert await composite.list_skill_resources("mine") == ["scripts/run.py"]

    @pytest.mark.asyncio
    async def test_missing_resource_and_unknown_skill(self) -> None:
        composite = CompositeSkillBackend(routes={"/user/": _StubBackend("user", {"mine": ["a.md"]})})

        with pytest.raises(FileNotFoundError):
            await composite.get_skill_resources("mine", "missing.md")
        assert await composite.list_skill_resources("ghost") == []


class TestWithRealLocalBackends:
    @staticmethod
    def _write_skill(root: Path, name: str, body: str) -> LocalSkillBackend:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} skill\n---\n{body}\n", encoding="utf-8"
        )
        return LocalSkillBackend(root)

    @pytest.mark.asyncio
    async def test_every_listed_skill_has_retrievable_content(self, tmp_path: Path) -> None:
        user = self._write_skill(tmp_path / "user", "mine", "# mine\n\nuser body")
        system = self._write_skill(tmp_path / "system", "shipped", "# shipped\n\nsystem body")
        composite = CompositeSkillBackend(routes={"/user/": user}, default=system)

        skills = await composite.list_skills()
        assert {skill.name for skill in skills} == {"mine", "shipped"}
        for skill in skills:
            content = await composite.get_skill_content(skill.storage_skill_id or skill.name)
            assert f"# {skill.name}" in content
