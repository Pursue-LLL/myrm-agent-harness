"""LLM 回复 JSON 容错解析模块（通用部分）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- json (stdlib): 严格 JSON 解析 + 结构化修复
- json_repair (optional): 脏 JSON 兜底修复（单引号 / 无引号 key / 内联注释）

[OUTPUT]
- parse_llm_json_object(): 从 LLM 回复容错提取 JSON 对象（fence / prose / 裸控制字符 / 尾逗号 / 多候选取末 / require_key 过滤）
- parse_llm_json_list(): 从 LLM 回复容错提取 JSON 数组（同上）

[POS]
Robust LLM JSON extraction. Business-config-independent helpers shared by all verifier/semantic layers.

"""

import json
import re
from collections.abc import Callable, Iterable
from typing import cast

_json_repair_loads: Callable[..., object] | None = None
try:
    from json_repair import loads as _loads

    _json_repair_loads = cast(Callable[..., object], _loads)
except ImportError:  # pragma: no cover - graceful degradation when dep absent
    pass


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _escape_control_chars_in_strings(text: str) -> str:
    """Escape unescaped control characters inside JSON string literals.

    JSON forbids raw control characters (code points < 0x20) inside string
    literals. Reasoning providers occasionally emit bare newlines or tabs,
    so they are rewritten to the standard short escapes (``\\n``/``\\t``)
    and any other control character to ``\\uXXXX``.
    """
    out: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if in_string:
            if escape_next:
                out.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                out.append(ch)
                escape_next = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
            continue
        if ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas inside JSON containers.

    LLMs occasionally serialize nested structures with trailing commas,
    e.g. ``[1, 2,]`` or ``{"a": 1,}``. A comma directly before ``}`` or
    ``]`` outside a string literal is never valid JSON, so dropping it is
    always safe. Repeated passes handle runs like ``{"a": 1,,}``.
    """
    previous: str | None = None
    while text != previous:
        previous = text
        out: list[str] = []
        in_string = False
        escape_next = False
        for ch in text:
            if in_string:
                out.append(ch)
                if escape_next:
                    escape_next = False
                elif ch == "\\":
                    escape_next = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                out.append(ch)
                continue
            if ch in " \t\r\n":
                out.append(ch)
                continue
            if ch in "}]":
                i = len(out) - 1
                while i >= 0 and out[i] in " \t\r\n":
                    i -= 1
                if i >= 0 and out[i] == ",":
                    del out[i:]
            out.append(ch)
        text = "".join(out)
    return text


def _iter_json_blocks(text: str, open_ch: str, close_ch: str) -> Iterable[str]:
    """Yield every balanced ``{open_ch}...{close_ch}`` block in ``text``.

    A single state-machine pass that respects string literals, escape
    sequences, and nesting, and ignores orphan closing tokens outside any
    block. This lets callers inspect *all* candidate blocks instead of
    committing to the first opener (which reasoning providers occasionally
    precede with a format example before the real result).

    Both double- and single-quoted strings are recognized, but a single
    quote only opens a string *inside* a container (``depth > 0``): outside
    one it is prose apostrophe (e.g. ``it's a test {a: 1}``) and must not
    swallow the object that follows. Being single-quote aware is what keeps
    a ``}`` inside ``{'a': 'x}y'}`` from truncating the candidate block —
    otherwise the repair tier would salvage the truncated fragment and
    silently drop data.
    """
    depth = 0
    start = -1
    quote: str | None = None
    escape_next = False
    for i, ch in enumerate(text):
        if quote is not None:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == quote:
                quote = None
            continue
        if ch == '"':
            quote = '"'
        elif ch == "'" and depth > 0:
            quote = "'"
        elif ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                yield text[start : i + 1]
                start = -1


def _iter_json_objects(text: str) -> Iterable[str]:
    """Yield every balanced ``{...}`` object in ``text``."""
    yield from _iter_json_blocks(text, "{", "}")


def _iter_json_arrays(text: str) -> Iterable[str]:
    """Yield every balanced ``[...]`` array in ``text``."""
    yield from _iter_json_blocks(text, "[", "]")


def _iter_repair_candidates(content: str) -> Iterable[str]:
    """Yield structurally bounded JSON candidates for the repair pass.

    Every fence body plus every balanced object/array block — never the
    raw prose, so the repair pass only ever sees bounded structures and
    cannot fabricate objects out of surrounding narration. The balance
    scanner is single-quote aware (inside a container) so a closing brace
    inside a single-quoted string never truncates a candidate block.
    """
    stripped = content.strip()
    if not stripped:
        return
    for match in _JSON_FENCE_RE.finditer(stripped):
        body = match.group(1).strip()
        if body:
            yield body
    yield from _iter_json_objects(stripped)
    yield from _iter_json_arrays(stripped)


def _try_load(text: str) -> object | None:
    """Return ``json.loads(text)`` or ``None`` when the text is malformed.

    ``RecursionError`` is caught alongside ``JSONDecodeError``: deeply
    nested (but syntactically valid) output exceeds the C parser's stack
    budget and must degrade to the next tier instead of crashing the
    extraction chain.
    """
    try:
        return cast(object | None, json.loads(text))
    except (json.JSONDecodeError, RecursionError):
        return None


def _try_parse_structural(candidate: str) -> object | None:
    """Try strict JSON, then two structural repairs (control chars, commas)."""
    parsed = _try_load(candidate)
    if parsed is None:
        escaped = _escape_control_chars_in_strings(candidate)
        parsed = _try_load(escaped)
        if parsed is None:
            parsed = _try_load(_strip_trailing_commas(escaped))
    return parsed


# json_repair's internal parser recursion budget; beyond this depth it
# degrades to quadratic time and then fails, so skip the repair tier.
_REPAIR_MAX_DEPTH = 512


def _repair_nesting_depth(candidate: str) -> int:
    """Return the maximum ``{``/``[`` nesting depth outside strings.

    Mirrors json_repair's own parse model — it tolerates both single- and
    double-quoted strings, so the budget check respects both quote kinds
    and never penalizes legitimate quoted fragments.
    """
    depth = 0
    max_depth = 0
    quote: str | None = None
    escape_next = False
    for ch in candidate:
        if quote is not None:
            if escape_next:
                escape_next = False
            elif ch == "\\":
                escape_next = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "{[":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in "}]" and depth > 0:
            depth -= 1
    return max_depth


def _try_load_repair(candidate: str) -> object | None:
    """Salvage a bounded candidate with the json_repair fallback tier.

    json_repair is the de-facto community standard for malformed LLM
    output: it tolerates single-quoted strings, unquoted keys, inline
    comments and Python-style booleans. Returns ``None`` when the text is
    hopeless or the dependency is unavailable (graceful degradation).
    """
    if _json_repair_loads is None:
        return None
    if _repair_nesting_depth(candidate) > _REPAIR_MAX_DEPTH:
        return None
    try:
        # skip_json_loads: the structural tier already failed with
        # json.loads, so skip the identical doomed pre-validation inside
        # json_repair and jump straight to repair.
        return _json_repair_loads(candidate, skip_json_loads=True)
    except (ValueError, TypeError, RecursionError):
        return None


def _iter_parsed_containers(
    content: str,
) -> Iterable[dict[str, object] | list[object]]:
    """Yield every dict or list recoverable from ``content``.

    Each structurally bounded candidate (fence body, balanced object/array)
    is tried strict-first, then with two structural repairs (unescaped
    control characters inside string literals, trailing commas), then with
    a third-party repair pass (json_repair) covering artifacts like
    single-quoted strings, unquoted keys and inline comments — matching
    what reasoning and local models actually emit. Raw prose is never a
    candidate, so surrounding narration is not "repaired" into a phantom
    object.
    """
    stripped = content.strip()
    if not stripped:
        return
    for candidate in _iter_repair_candidates(content):
        parsed = _try_parse_structural(candidate)
        if parsed is None:
            parsed = _try_load_repair(candidate)
        if isinstance(parsed, (dict, list)):
            yield parsed


def parse_llm_json_object(
    content: str,
    *,
    require_key: str | None = None,
) -> dict[str, object] | None:
    """Parse a JSON object out of an LLM reply.

    Tolerates the artifacts reasoning providers actually emit: markdown
    fences, prose framing around the object, unescaped control characters
    inside string literals (e.g. bare newlines or tabs), trailing commas,
    and multiple objects/fences where the last one is the real result
    (format examples preceding the actual result). When structural parsing
    fails, a json_repair fallback salvages single-quoted strings, unquoted
    keys and inline comments. When several objects are recoverable, the
    *last* parseable dict wins, matching how reasoning providers tend to
    end with the final verdict. Returns ``None`` when no object can be
    recovered.

    When ``require_key`` is given, only objects carrying that key are
    considered and the *last* such object wins — letting callers express
    contracts like "a verdict that must contain ``done``" without
    iterating candidates themselves.
    """
    parsed_last: dict[str, object] | None = None
    for parsed in _iter_parsed_containers(content):
        if isinstance(parsed, dict) and (require_key is None or require_key in parsed):
            parsed_last = parsed
    return parsed_last


def parse_llm_json_list(content: str) -> list[object] | None:
    """Parse a JSON array out of an LLM reply.

    Mirrors :func:`parse_llm_json_object` for arrays: tolerates fences,
    prose framing, unescaped control characters inside string literals,
    trailing commas, json_repair-salvageable artifacts, and multiple
    arrays where the last one is the real result. Returns ``None`` when
    no array can be recovered.
    """
    parsed_last: list[object] | None = None
    for parsed in _iter_parsed_containers(content):
        if isinstance(parsed, list):
            parsed_last = parsed
    return parsed_last
