"""Zero-dependency, offline semantic synonym expansion engine.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- OfflineSynonymExpander: Zero-dependency, offline semantic synonym expansion engine.

[POS]
Zero-dependency, offline semantic synonym expansion engine.
"""

import re

_SAFE_WORD_REGEX = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class OfflineSynonymExpander:
    """Zero-dependency, offline semantic synonym expansion engine.

    Expands query keywords into disjunctive FTS5 MATCH expressions (e.g. `(hotpot OR 打边炉)`),
    preventing synonym blindness without calling remote LLM/embedding APIs.
    """

    def __init__(self) -> None:
        self._synonym_map: dict[str, set[str]] = {}
        self._initialize_builtins()

    def _initialize_builtins(self) -> None:
        """Seed high-signal engineering and domain synonym clusters."""
        defaults: list[tuple[str, list[str]]] = [
            ("auth", ["authentication", "jwt", "token", "login"]),
            ("jwt", ["token", "bearer", "auth"]),
            ("oom", ["out_of_memory", "memory_leak", "heap_overflow"]),
            ("db", ["database", "sqlite", "postgres", "storage"]),
            ("sqlite", ["fts5", "embedded_db", "database"]),
            ("api", ["endpoint", "rest", "router", "route"]),
            ("error", ["exception", "failure", "fault", "bug"]),
            ("concurrency", ["async", "thread", "parallel", "coroutine"]),
            ("hotpot", ["打边炉", "火锅", "暖锅"]),
            ("火锅", ["打边炉", "hotpot"]),
        ]
        for primary, syns in defaults:
            self.register_synonyms(primary, syns)

    def register_synonyms(self, primary_term: str, synonyms: list[str]) -> None:
        """Register or extend bidirectional synonym clusters."""
        p_norm = primary_term.strip().lower()
        if not p_norm:
            return

        syn_set = self._synonym_map.setdefault(p_norm, set())
        for syn in synonyms:
            s_norm = syn.strip().lower()
            if s_norm and s_norm != p_norm:
                syn_set.add(s_norm)
                # Bidirectional mapping
                self._synonym_map.setdefault(s_norm, set()).add(p_norm)

    def get_synonyms(self, term: str) -> list[str]:
        """Return all registered synonyms for a specific keyword."""
        return sorted(self._synonym_map.get(term.strip().lower(), set()))

    def total_terms(self) -> int:
        """Return count of unique indexed keyword nodes in the synonym graph."""
        return len(self._synonym_map)

    def expand_query(self, raw_query: str) -> tuple[str, list[str]]:
        """Expand search terms into a safe SQLite FTS5 disjunctive MATCH expression.

        Returns (fts5_match_clause, expanded_terms_collected).
        """
        words = _SAFE_WORD_REGEX.findall(raw_query.lower())
        if not words:
            return "", []

        clauses: list[str] = []
        expanded_terms: list[str] = []

        for word in words:
            synonyms = self._synonym_map.get(word, set())
            if synonyms:
                # Group term with its synonyms: (word OR syn1 OR syn2)
                term_group = [f'"{word}"']
                for syn in sorted(synonyms):
                    # Sanitize synonym to alphanumeric or underscore
                    clean_syn = "".join(c for c in syn if c.isalnum() or c in ("_", "\u4e00-\u9fff"))
                    if clean_syn:
                        term_group.append(f'"{clean_syn}"')
                        expanded_terms.append(clean_syn)
                clauses.append(f"({' OR '.join(term_group)})")
            else:
                clauses.append(f'"{word}"')

        fts5_expr = " AND ".join(clauses)
        return fts5_expr, expanded_terms
