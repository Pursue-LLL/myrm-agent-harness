"""Similar-path hints and Unicode normalization healing when a requested file or directory is not found.

[OUTPUT]
- generate_unicode_path_candidates: Generate 7-stage normalized candidate path variations.
- find_existing_unicode_path: Probe and find an existing on-disk path across Unicode normalizations.
- levenshtein_distance_bounded: Bounded Levenshtein edit distance computation (<= max_dist).
- suggest_similar_paths: Return closest paths under parent dirs using Levenshtein-2 and similarity.
- format_path_not_found_hint: Format informative error message with 'Did you mean' suggestions.

[POS]
File-search and file-ops UX helper for mistyped, Unicode-decomposed, or moved workspace paths.
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

from myrm_agent_harness.core.security.path_security import is_blocked_device_path

_QUOTE_STRIP_RE = re.compile(r"^[\s\"'“”‘’`]+|[\s\"'“”‘’`]+$")
_SLASH_COLLAPSE_RE = re.compile(r"[\\/]+")

_PATH_UNICODE_MAP: dict[str, str] = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # non-breaking space
    "\u200b": "",  # zero-width space
    "\u200c": "",  # zero-width non-joiner
    "\u200d": "",  # zero-width joiner
    "\ufeff": "",  # BOM / zero-width no-break space
    "\uff0f": "/",  # fullwidth solidus
    "\uff3c": "/",  # fullwidth reverse solidus
}

_PATH_UNICODE_RE = re.compile("|".join(re.escape(k) for k in _PATH_UNICODE_MAP))


def generate_unicode_path_candidates(raw_path: str) -> list[str]:
    """Generate up to 7 distinct candidate path variants via Unicode normalization chains.

    Chain stages:
    0. Surrounding quotes & whitespace stripped
    1. NFC normalization (Canonical Decomposition followed by Canonical Composition)
    2. NFD normalization (Canonical Decomposition - macOS APFS/HFS+ native form)
    3. NFKC normalization (Compatibility Decomposition followed by Canonical Composition)
    4. NFKD normalization (Compatibility Decomposition)
    5. Custom character substitution (curly quotes, NBSP, zero-width spaces, dashes)
    6. NFKC + custom character substitution combined
    7. Slash normalization (collapsing redundant separators)

    Returns a deduplicated list of non-empty candidates preserving stage priority.
    """
    if not raw_path:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(cand: str) -> None:
        cand_clean = cand.strip()
        if cand_clean and cand_clean not in seen:
            seen.add(cand_clean)
            candidates.append(cand_clean)

    # Stage 0: Stripped raw
    stage0 = _QUOTE_STRIP_RE.sub("", raw_path)
    _add(stage0)
    _add(raw_path)

    base = stage0 or raw_path

    # Stage 1: NFC
    _add(unicodedata.normalize("NFC", base))

    # Stage 2: NFD
    _add(unicodedata.normalize("NFD", base))

    # Stage 3: NFKC
    _add(unicodedata.normalize("NFKC", base))

    # Stage 4: NFKD
    _add(unicodedata.normalize("NFKD", base))

    # Stage 5: Custom Unicode character mapping
    mapped = _PATH_UNICODE_RE.sub(lambda m: _PATH_UNICODE_MAP[m.group()], base)
    _add(mapped)

    # Stage 6: Combined mapping + NFKC/NFC
    _add(unicodedata.normalize("NFC", mapped))
    _add(unicodedata.normalize("NFKC", mapped))

    # Stage 7: Collapsed slashes
    for c in list(candidates):
        collapsed = _SLASH_COLLAPSE_RE.sub("/", c)
        _add(collapsed)

    return candidates


def find_existing_unicode_path(target_path: str, base_dir: str | None = None) -> str | None:
    """Probe file system across Unicode normalization candidates to find an existing path.

    Returns the first matching on-disk relative/absolute path candidate if found,
    or None if no variation exists or if the candidate refers to a blocked device.
    """
    if not target_path or is_blocked_device_path(target_path):
        return None

    candidates = generate_unicode_path_candidates(target_path)

    for cand in candidates:
        if is_blocked_device_path(cand):
            continue

        # If base_dir provided, probe relative to base_dir
        if base_dir:
            full_path = os.path.join(base_dir, cand)
            if is_blocked_device_path(full_path):
                continue
            if os.path.exists(full_path):
                return cand

        # Direct path probe
        if os.path.exists(cand):
            return cand

    return None


def levenshtein_distance_bounded(s1: str, s2: str, max_dist: int = 2) -> int:
    """Compute Levenshtein edit distance between s1 and s2 with early boundary cutoff.

    Returns the edit distance, or `max_dist + 1` as soon as it is proven that
    distance exceeds `max_dist`.
    """
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > max_dist:
        return max_dist + 1

    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    prev = list(range(len1 + 1))
    for i2, c2 in enumerate(s2, 1):
        curr = [i2] * (len1 + 1)
        min_in_row = curr[0]
        for i1, c1 in enumerate(s1, 1):
            cost = 0 if c1 == c2 else 1
            curr[i1] = min(
                curr[i1 - 1] + 1,
                prev[i1] + 1,
                prev[i1 - 1] + cost,
            )
            if curr[i1] < min_in_row:
                min_in_row = curr[i1]
        if min_in_row > max_dist:
            return max_dist + 1
        prev = curr

    return prev[len1]


def suggest_similar_paths(
    target_path: str,
    *,
    max_suggestions: int = 3,
) -> list[str]:
    """Return up to ``max_suggestions`` paths similar to ``target_path``.

    Uses Bounded Levenshtein-2 ranking on basenames in parent and grandparent
    directories, with fallback to SequenceMatcher for fuzzy similarity.
    """
    norm = os.path.normpath(target_path)
    parent = os.path.dirname(norm) or "."
    basename = os.path.basename(norm)
    if not basename:
        return []

    search_dirs: list[str] = [parent]
    grandparent = os.path.dirname(parent)
    if grandparent and grandparent != parent:
        search_dirs.append(grandparent)

    scored_candidates: list[tuple[int, float, str]] = []
    seen: set[str] = set()

    for directory in search_dirs:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            continue
        try:
            entries = [entry.name for entry in dir_path.iterdir()]
        except OSError:
            continue

        target_base_lower = basename.lower()
        for entry_name in entries:
            candidate_path = os.path.join(directory, entry_name)
            if candidate_path in seen or is_blocked_device_path(candidate_path):
                continue

            entry_lower = entry_name.lower()
            # Bounded Levenshtein distance (max 2 edits)
            dist = levenshtein_distance_bounded(target_base_lower, entry_lower, max_dist=2)
            if dist <= 2:
                # Primary ranking: smallest distance, then SequenceMatcher ratio
                ratio = SequenceMatcher(None, target_base_lower, entry_lower).ratio()
                scored_candidates.append((dist, -ratio, candidate_path))
                seen.add(candidate_path)

        # Fallback if no Levenshtein-2 matches found
        if not scored_candidates:
            close_matches = get_close_matches(basename, entries, n=max_suggestions, cutoff=0.6)
            for match in close_matches:
                cand = os.path.join(directory, match)
                if cand not in seen and not is_blocked_device_path(cand):
                    seen.add(cand)
                    scored_candidates.append((3, 0.0, cand))

    scored_candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored_candidates[:max_suggestions]]


def format_path_not_found_hint(target_path: str, suggestions: list[str]) -> str:
    """Format informative error message with suggested similar paths."""
    if not suggestions:
        return f"The path '{target_path}' does not exist. Please check the path and try again."
    joined = ", ".join(f"'{s}'" for s in suggestions)
    return f"The path '{target_path}' does not exist. Did you mean: {joined}?"
