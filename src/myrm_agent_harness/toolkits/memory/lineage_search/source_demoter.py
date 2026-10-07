# [POS]: myrm_agent_harness/toolkits/memory/lineage_search/source_demoter.py
# [INPUT]: Raw search hits, session metadata, filtering and demotion policies
# [OUTPUT]: Filtered and demoted candidate list preventing recall blindness (PR #19434)

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.lineage_search.models import (
    RawSearchHit,
    SessionMeta,
    SessionSourceKind,
)

_HIDDEN_SOURCES: frozenset[SessionSourceKind] = frozenset(
    {
        SessionSourceKind.SUBAGENT,
        SessionSourceKind.KANBAN,
        SessionSourceKind.INTERNAL_WORKER,
    }
)

_DEMOTED_SOURCES: frozenset[SessionSourceKind] = frozenset(
    {
        SessionSourceKind.CRON,
    }
)


class SourceDemoterAndFilter:
    """Implements source-aware filtering and demotion policies inspired by Hermes Agent PR #19434.

    Prevents recurring cron/automation vocabulary from starving out interactive sessions
    under BM25 scoring while keeping cron jobs discoverable when they are the only match.
    """

    def __init__(self, demotion_penalty: float = 0.5) -> None:
        self._demotion_penalty = demotion_penalty

    @staticmethod
    def is_hidden(source: SessionSourceKind, include_hidden: bool = False) -> bool:
        """Report whether session provenance should be concealed from discovery."""
        if include_hidden:
            return False
        return source in _HIDDEN_SOURCES

    @staticmethod
    def is_demoted(source: SessionSourceKind) -> bool:
        """Report whether session provenance should be ranked below interactive sessions."""
        return source in _DEMOTED_SOURCES

    def filter_and_demote(
        self,
        hits: Sequence[RawSearchHit],
        session_metas: dict[str, SessionMeta],
        include_hidden: bool = False,
    ) -> list[RawSearchHit]:
        """Filter out internal noise workers and rank interactive sessions above cron jobs."""
        interactive_hits: list[RawSearchHit] = []
        demoted_hits: list[RawSearchHit] = []

        for hit in hits:
            meta = session_metas.get(hit.session_id)
            source = meta.source if meta else hit.source

            # Step 1: Conceal hidden internal worker sources
            if self.is_hidden(source, include_hidden=include_hidden):
                continue

            # Step 2: Separate demoted automation (cron) from interactive sessions
            if self.is_demoted(source):
                # Demoted hit retains lower adjusted score for sub-sorting
                demoted_hits.append(hit)
            else:
                interactive_hits.append(hit)

        # Interactive sessions always precede demoted cron hits
        # Demoting — not excluding — keeps cron reachable when it's the only match (#19434)
        interactive_sorted = sorted(interactive_hits, key=lambda h: h.score, reverse=True)
        demoted_sorted = sorted(demoted_hits, key=lambda h: h.score, reverse=True)

        return interactive_sorted + demoted_sorted
