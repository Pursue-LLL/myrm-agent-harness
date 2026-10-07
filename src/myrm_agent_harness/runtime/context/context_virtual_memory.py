"""Context Virtual Memory Manager and CoALA 4-Quadrant Structured Note-Taking Engine.

Implements LLM OS virtual memory paging (RAM vs Disk) and CoALA quadrant coordination:
- Working Memory (Context RAM): Directly rendered in current LLM prompt
- External Memory (Disk / Paged Out): Swapped out to prevent context bloat,
  and swapped in just-in-time (JIT) based on keyword or note type relevance.

[INPUT]
- runtime.context.context_engineering_types::ContextRemediationConfig, NoteType, ScenarioProfile,
  ScenarioType, StructuredNote (POS: Context engineering types and data protocols for ReAct trap remediation
  and ACI design.)

[OUTPUT]
- ContextVirtualMemoryManager: Manages virtual memory paging and 4-quadrant structured notes for
  long-running agents.

[POS]
Context Virtual Memory Manager and CoALA 4-Quadrant Structured Note-Taking Engine.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.context_engineering_types import (
    ContextRemediationConfig,
    NoteType,
    ScenarioProfile,
    ScenarioType,
    StructuredNote,
)


class ContextVirtualMemoryManager:
    """Manages virtual memory paging and 4-quadrant structured notes for long-running agents."""

    def __init__(self, scenario: ScenarioType = ScenarioType.GENERAL_OFFICE_CODING) -> None:
        self.scenario = scenario
        self._ram_notes: dict[str, StructuredNote] = {}
        self._disk_notes: dict[str, StructuredNote] = {}
        self._profile = self._build_scenario_profile(scenario)

    @property
    def profile(self) -> ScenarioProfile:
        """Active scenario profile."""
        return self._profile

    def add_note(
        self,
        note_id: str,
        note_type: NoteType,
        title: str,
        content: str,
        turn_index: int,
        tags: set[str] | None = None,
        load_to_ram: bool = True,
    ) -> StructuredNote:
        """Create and register a new structured note."""
        note = StructuredNote(
            note_id=note_id,
            note_type=note_type,
            title=title,
            content=content,
            turn_index=turn_index,
            tags=tags or set(),
        )

        if load_to_ram:
            self._ram_notes[note_id] = note
            self._disk_notes.pop(note_id, None)
        else:
            self._disk_notes[note_id] = note
            self._ram_notes.pop(note_id, None)

        return note

    def page_out(self, note_id: str) -> bool:
        """Swap note from Context RAM to Disk storage."""
        if note_id in self._ram_notes:
            note = self._ram_notes.pop(note_id)
            self._disk_notes[note_id] = note
            return True
        return False

    def page_in(self, note_id: str) -> bool:
        """Swap note from Disk storage into active Context RAM."""
        if note_id in self._disk_notes:
            note = self._disk_notes.pop(note_id)
            self._ram_notes[note_id] = note
            return True
        return False

    def page_in_by_query(self, query: str, limit: int = 3) -> list[StructuredNote]:
        """JIT retrieve and page-in relevant notes from Disk matching search tokens."""
        tokens = {t.lower() for t in query.split() if len(t) >= 2}
        matches: list[StructuredNote] = []

        for note_id, note in list(self._disk_notes.items()):
            text = f"{note.title} {note.content} {' '.join(note.tags)}".lower()
            if any(tok in text for tok in tokens):
                self.page_in(note_id)
                matches.append(note)
                if len(matches) >= limit:
                    break

        return matches

    def get_ram_notes(self) -> list[StructuredNote]:
        """Return all notes currently resident in active RAM."""
        return list(self._ram_notes.values())

    def get_disk_notes(self) -> list[StructuredNote]:
        """Return all notes paged out to disk."""
        return list(self._disk_notes.values())

    def render_active_memory_xml(self) -> str:
        """Render active RAM notes into structured XML context block."""
        if not self._ram_notes:
            return ""

        lines: list[str] = ["<structured_memory_notes>"]
        for note in self._ram_notes.values():
            tags_attr = f' tags="{",".join(sorted(note.tags))}"' if note.tags else ""
            lines.append(
                f'  <note id="{note.note_id}" type="{note.note_type.value}" '
                f'turn="{note.turn_index}"{tags_attr}>\n'
                f"    <title>{note.title}</title>\n"
                f"    <content>{note.content}</content>\n"
                f"  </note>"
            )
        lines.append("</structured_memory_notes>")
        return "\n".join(lines)

    def _build_scenario_profile(self, scenario: ScenarioType) -> ScenarioProfile:
        """Construct domain-specific context remediation and rule profile."""
        if scenario == ScenarioType.CUSTOMER_SERVICE:
            return ScenarioProfile(
                scenario=scenario,
                config=ContextRemediationConfig(
                    fold_tool_length_threshold=300,
                    keep_recent_raw_tool_turns=2,
                    reanchor_turn_interval=6,
                    max_active_thoughts_turns=2,
                ),
                core_rules=[
                    "Always confirm user consent before finalizing payments or account mutations.",
                    "Maintain polite, professional tone and do not hallucinate policy terms.",
                ],
                max_recent_files=2,
            )
        elif scenario == ScenarioType.DEEP_RESEARCH:
            return ScenarioProfile(
                scenario=scenario,
                config=ContextRemediationConfig(
                    fold_tool_length_threshold=800,
                    keep_recent_raw_tool_turns=3,
                    reanchor_turn_interval=12,
                    max_active_thoughts_turns=4,
                ),
                core_rules=[
                    "Attribute all empirical claims to cited primary research or web sources.",
                    "Cross-validate discrepancies across multiple sources before concluding.",
                ],
                max_recent_files=10,
            )
        else:  # GENERAL_OFFICE_CODING
            return ScenarioProfile(
                scenario=scenario,
                config=ContextRemediationConfig(
                    fold_tool_length_threshold=500,
                    keep_recent_raw_tool_turns=1,
                    reanchor_turn_interval=8,
                    max_active_thoughts_turns=3,
                ),
                core_rules=[
                    "Ensure code changes are 100% type-safe with 0 Any and strict PEP8 compliance.",
                    "Verify all modifications with automated unit tests before reporting completion.",
                ],
                max_recent_files=5,
            )
