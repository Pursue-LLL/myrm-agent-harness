"""Known-pitfalls tail injection: rendering contract, lookup registration, document pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.skills.select.skill_document_loader import get_skill_document
from myrm_agent_harness.agent.skills.runtime.trap_injection import (
    TrapRecord,
    inject_known_pitfalls,
    inject_traps,
    set_trap_lookup,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

BASE = "# Skill\n\nDo the thing.\n"
SECTION_HEAD = "\n\n---\n## Known Pitfalls\n\n"


@pytest.fixture(autouse=True)
def _reset_lookup() -> Iterator[None]:
    set_trap_lookup(None)
    yield
    set_trap_lookup(None)


class TestInjectKnownPitfalls:
    def test_orders_by_severity_then_occurrence_and_marks_severity(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "medium", "description": "m-many", "occurrence_count": 10},
            {"severity": "critical", "description": "c-few", "mitigation": "stop", "occurrence_count": 1},
            {"severity": "high", "description": "h-few", "occurrence_count": 1},
            {"severity": "high", "description": "h-many", "mitigation": "retry", "occurrence_count": 7},
            {"severity": "low", "description": "ignored", "occurrence_count": 99},
            {"severity": "critical", "description": "c-many", "occurrence_count": 5},
        ]

        assert inject_known_pitfalls(BASE, traps) == (
            f"{BASE}{SECTION_HEAD}"
            "- [!!!] c-many\n- [!!!] c-few → stop\n- [!!] h-many → retry\n- [!!] h-few\n- [!] m-many\n"
        )

    def test_exact_output_for_single_trap(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "high", "description": "rate limit", "mitigation": "sleep 1s", "occurrence_count": 2}
        ]

        assert inject_known_pitfalls(BASE, traps) == f"{BASE}{SECTION_HEAD}- [!!] rate limit → sleep 1s\n"

    def test_original_content_stays_a_byte_prefix(self) -> None:
        traps: list[TrapRecord] = [{"severity": "critical", "description": "x"}]

        assert inject_known_pitfalls(BASE, traps).startswith(BASE)

    def test_entry_without_mitigation_has_no_arrow(self) -> None:
        traps: list[TrapRecord] = [{"severity": "medium", "description": "careful"}]

        assert inject_known_pitfalls(BASE, traps) == f"{BASE}{SECTION_HEAD}- [!] careful\n"

    def test_unicode_description_and_mitigation_preserved(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "critical", "description": "路径 /tmp → 失败", "mitigation": "改用相对路径"}
        ]

        assert inject_known_pitfalls(BASE, traps) == f"{BASE}{SECTION_HEAD}- [!!!] 路径 /tmp → 失败 → 改用相对路径\n"

    def test_caps_at_five_most_frequent_by_default(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "medium", "description": f"t{i}", "occurrence_count": i} for i in range(1, 9)
        ]

        result = inject_known_pitfalls(BASE, traps)

        assert result.endswith("- [!] t8\n- [!] t7\n- [!] t6\n- [!] t5\n- [!] t4\n")
        assert "t3" not in result

    def test_max_traps_override(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "medium", "description": f"t{i}", "occurrence_count": i} for i in range(1, 9)
        ]

        assert inject_known_pitfalls(BASE, traps, max_traps=2).endswith("- [!] t8\n- [!] t7\n")

    def test_equal_rank_and_count_keep_input_order(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "high", "description": name, "occurrence_count": 4} for name in ("first", "second", "third")
        ]

        assert inject_known_pitfalls(BASE, traps).endswith("- [!!] first\n- [!!] second\n- [!!] third\n")

    def test_missing_occurrence_count_sorts_as_zero(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "high", "description": "a"},
            {"severity": "high", "description": "b", "occurrence_count": 1},
        ]

        assert inject_known_pitfalls(BASE, traps).endswith("- [!!] b\n- [!!] a\n")

    def test_non_integer_occurrence_count_does_not_break_rendering(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "high", "description": "garbled", "occurrence_count": "3"},
            {"severity": "high", "description": "clean", "occurrence_count": 1},
        ]

        assert inject_known_pitfalls(BASE, traps).endswith("- [!!] clean\n- [!!] garbled\n")

    @pytest.mark.parametrize(
        "traps",
        [
            pytest.param([], id="empty"),
            pytest.param([{"severity": "low", "description": "minor", "occurrence_count": 9}], id="low-only"),
            pytest.param([{"severity": "weird", "description": "?"}], id="unknown-severity"),
            pytest.param([{"description": "no severity"}], id="missing-severity"),
        ],
    )
    def test_content_unchanged_when_nothing_qualifies(self, traps: list[TrapRecord]) -> None:
        assert inject_known_pitfalls(BASE, traps) == BASE

    def test_input_traps_are_not_reordered(self) -> None:
        traps: list[TrapRecord] = [
            {"severity": "medium", "description": "m"},
            {"severity": "critical", "description": "c"},
        ]

        inject_known_pitfalls(BASE, traps)

        assert [t["description"] for t in traps] == ["m", "c"]


class TestInjectTraps:
    def test_without_registered_lookup_content_is_unchanged(self) -> None:
        assert inject_traps("demo", BASE) == BASE

    def test_registered_lookup_receives_skill_name_and_appends_section(self) -> None:
        seen: list[str] = []

        def lookup(skill_name: str) -> list[TrapRecord]:
            seen.append(skill_name)
            return [{"severity": "high", "description": "rate limit"}]

        set_trap_lookup(lookup)

        assert inject_traps("my-skill", BASE) == f"{BASE}{SECTION_HEAD}- [!!] rate limit\n"
        assert seen == ["my-skill"]

    def test_lookup_without_traps_leaves_content_unchanged(self) -> None:
        set_trap_lookup(lambda _name: [])

        assert inject_traps("demo", BASE) == BASE

    def test_failing_lookup_never_blocks_loading(self) -> None:
        def boom(_name: str) -> list[TrapRecord]:
            raise RuntimeError("db down")

        set_trap_lookup(boom)

        assert inject_traps("demo", BASE) == BASE

    def test_clearing_lookup_stops_injection(self) -> None:
        set_trap_lookup(lambda _name: [{"severity": "high", "description": "x"}])
        set_trap_lookup(None)

        assert inject_traps("demo", BASE) == BASE


class TestSkillDocumentPipeline:
    async def test_pitfalls_follow_sop_and_precede_l1_footer(self) -> None:
        skill = SkillMetadata(name="demo", description="demo skill", storage_skill_id="demo")
        backend = AsyncMock()
        backend.get_skill_content.return_value = "# demo\n\nBody."
        set_trap_lookup(
            lambda _name: [{"severity": "critical", "description": "never rm -rf", "mitigation": "dry-run"}]
        )

        with patch(
            "myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer.build_l1_disclosure_footer",
            new=AsyncMock(return_value="\n[FOOTER]"),
        ):
            document = await get_skill_document(skill, backend)

        assert document == f"# demo\n\nBody.{SECTION_HEAD}- [!!!] never rm -rf → dry-run\n\n[FOOTER]"

    async def test_document_is_unchanged_when_no_lookup_registered(self) -> None:
        skill = SkillMetadata(name="demo", description="demo skill", storage_skill_id="demo")
        backend = AsyncMock()
        backend.get_skill_content.return_value = "# demo\n\nBody."

        with patch(
            "myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer.build_l1_disclosure_footer",
            new=AsyncMock(return_value=""),
        ):
            document = await get_skill_document(skill, backend)

        assert document == "# demo\n\nBody."
