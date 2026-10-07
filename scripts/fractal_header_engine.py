"""Synthesise ``[INPUT]/[OUTPUT]/[POS]`` module headers (fractal doc level L4) from the AST.

Everything written is derived from what the author already wrote - module and class
docstrings, import statements and public names - so the result is a factual, mechanical
first draft that satisfies ``check_fractal_docs.py`` and is meant to be refined by hand.
Existing docstring prose is never rewritten: the sections are appended before the closing
quotes, and an AST fingerprint guard proves that only the module docstring changed.

[INPUT]
- Python standard library only (ast, textwrap, warnings)

[OUTPUT]
- add_header(): return the module source with the three sections added to its docstring
- module_summary(): one-line description reused by ``_ARCH.md`` rows
- HeaderError / HeaderResult: failure reason and result of ``add_header``

[POS]
Header half of scripts/fix_fractal_docs.py; produces the format already used across src/.
"""

from __future__ import annotations

import ast
import re
import sys
import textwrap
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PACKAGE = "myrm_agent_harness"
_WRAP_WIDTH = 110
_SUMMARY_LIMIT = 200
_MAX_OUTPUT_ITEMS = 15
_TYPES_SUFFIXES = ("types", "models", "schemas", "contracts")
_STDLIB = frozenset(sys.stdlib_module_names)
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_POS_RE = re.compile(r"\[POS\]:?[ \t]*(.*?)(?=\n\s*\[(?:INPUT|OUTPUT)\]|\Z)", re.DOTALL)
_PATH_LIKE_RE = re.compile(r"^[\w./-]+\.py$")
_CODING_RE = re.compile(r"^#.*coding[:=]")

_DefNode = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


class HeaderError(Exception):
    """The file cannot be rewritten safely; the message is shown to the user."""


@dataclass(frozen=True)
class HeaderResult:
    source: str
    summary: str


def add_header(source: str, path: Path, package_root: Path) -> HeaderResult:
    """Return ``source`` with ``[INPUT]/[OUTPUT]/[POS]`` added to (or created as) its module docstring."""
    if "\r" in source:
        raise HeaderError("CR/CRLF line endings are not supported")
    tree = _parse(source)
    summary = _summary(tree, path)
    sections = "\n".join(_sections(tree, path, package_root, summary))
    literal = _docstring_node(tree)
    if literal is not None and ast.get_docstring(tree):
        new_source = _append_sections(source, literal, sections)
    else:
        new_source = _insert_docstring(source, literal, f"{summary}\n\n{sections}")
    _verify(tree, new_source)
    return HeaderResult(new_source, summary)


def module_summary(path: Path) -> str:
    """One-line description of a module: its docstring prose, its ``[POS]`` text, else a synthesised one."""
    try:
        return _summary(_parse(path.read_text(encoding="utf-8")), path)
    except (HeaderError, OSError, UnicodeDecodeError):
        return _capitalise(_words(path.stem)) + "."


def _parse(source: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return ast.parse(source)
        except (SyntaxError, ValueError) as exc:
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            raise HeaderError(f"cannot parse with Python {version}: {exc}") from exc


def _docstring_node(tree: ast.Module) -> ast.Constant | None:
    if tree.body and isinstance(tree.body[0], ast.Expr):
        value = tree.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value
    return None


# --------------------------------------------------------------------------- summary


def _words(identifier: str) -> str:
    return identifier.replace("_", " ").strip()


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def _clean(text: str) -> str:
    """Single-line text that cannot alter docstring parsing (no backslashes, no triple quotes)."""
    return " ".join(text.replace("\\", "/").replace('"""', "'''").split())


def _shorten(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _sentence(text: str) -> str:
    return text if not text or text[-1] in ".!?。" else text + "."


def _prose_summary(doc: str) -> str:
    """First paragraph of a docstring, or ``""`` when it starts with a marker instead of prose."""
    text = _clean(doc.strip().split("\n\n", 1)[0])
    return "" if text.startswith("[") else _sentence(_shorten(text))


def _pos_summary(doc: str) -> str:
    match = _POS_RE.search(doc)
    text = _clean(match.group(1)) if match else ""
    return "" if _PATH_LIKE_RE.match(text) else _sentence(_shorten(text))


def _tokens(name: str) -> frozenset[str]:
    return frozenset(token.lower() for token in _TOKEN_RE.findall(name.replace("_", " ")))


def _primary_symbol_doc(tree: ast.Module, stem: str) -> str:
    """Docstring of the public symbol whose name best matches the module name (first one on ties)."""
    stem_tokens = _tokens(stem)
    best_score, best_doc = 0.0, ""
    fallback = ""
    for node in tree.body:
        if not isinstance(node, _DefNode) or node.name.startswith("_"):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        fallback = fallback or doc
        union = stem_tokens | _tokens(node.name)
        score = len(stem_tokens & _tokens(node.name)) / len(union) if union else 0.0
        if score > best_score:
            best_score, best_doc = score, doc
    return best_doc or fallback


def _synth_summary(tree: ast.Module, path: Path) -> str:
    stem = path.stem
    if stem == "__init__":
        return f"Package facade for {_words(path.parent.name)}."
    for suffix in _TYPES_SUFFIXES:
        if stem == suffix:
            return f"Types and models for {_words(path.parent.name)}."
        if stem.endswith(f"_{suffix}"):
            return f"Types and models for {_words(stem[: -len(suffix) - 1])}."
    summary = _prose_summary(_primary_symbol_doc(tree, stem))
    return summary or _capitalise(_words(stem)) + "."


def _summary(tree: ast.Module, path: Path) -> str:
    doc = ast.get_docstring(tree)
    if doc:
        return _prose_summary(doc) or _pos_summary(doc) or _synth_summary(tree, path)
    return _synth_summary(tree, path)


# ---------------------------------------------------------------------------- sections


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(
        text, width=_WRAP_WIDTH, subsequent_indent="  ", break_long_words=False, break_on_hyphens=False
    )


def _sections(tree: ast.Module, path: Path, package_root: Path, summary: str) -> list[str]:
    pos = textwrap.wrap(summary, width=_WRAP_WIDTH, break_long_words=False, break_on_hyphens=False)
    return [
        "[INPUT]",
        *_input_lines(tree, path, package_root),
        "",
        "[OUTPUT]",
        *_output_lines(tree),
        "",
        "[POS]",
        *pos,
    ]


def _resolve_import(node: ast.Import | ast.ImportFrom, package: tuple[str, ...]) -> list[tuple[str, list[str]]]:
    """Package-relative ``(module, names)`` pairs for imports that stay inside the harness."""
    if isinstance(node, ast.Import):
        return [
            (alias.name.removeprefix(f"{_PACKAGE}."), [])
            for alias in node.names
            if alias.name.startswith(f"{_PACKAGE}.")
        ]
    names = [alias.name for alias in node.names]
    if node.level == 0:
        module = node.module or ""
        if module == _PACKAGE:
            return [("", names)]
        if module.startswith(f"{_PACKAGE}."):
            return [(module.removeprefix(f"{_PACKAGE}."), names)]
        return []
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return []
    parts = (*package[:keep], *(node.module.split(".") if node.module else ()))
    return [(".".join(parts), names)]


def _third_party(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.ImportFrom):
        modules = [] if node.level or not node.module else [node.module]
    else:
        modules = [alias.name for alias in node.names]
    tops = (module.split(".")[0] for module in modules)
    return [top for top in tops if top != _PACKAGE and top not in _STDLIB]


@lru_cache(maxsize=512)
def _target_summary(package_root: Path, module: str) -> str:
    base = package_root.joinpath(*module.split(".")) if module else package_root
    candidate = base.with_suffix(".py")
    if candidate.is_file():
        return module_summary(candidate)
    init = base / "__init__.py"
    if init.is_file():
        doc = ast.get_docstring(_parse(init.read_text(encoding="utf-8")))
        return (_prose_summary(doc) or _pos_summary(doc)) if doc else ""
    return ""


def _input_lines(tree: ast.Module, path: Path, package_root: Path) -> list[str]:
    package = path.relative_to(package_root).parent.parts
    internal: dict[str, list[str]] = {}
    external: dict[str, None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for module, names in _resolve_import(node, package):
            known = internal.setdefault(module, [])
            known.extend(name for name in names if name not in known)
        external.update(dict.fromkeys(_third_party(node)))
    entries: list[str] = []
    for module, names in internal.items():
        label = f"{module}::{', '.join(names)}" if names else module
        pos = _target_summary(package_root, module)
        entries.append(f"{label} (POS: {pos})" if pos else label)
    if external:
        entries.append(f"Third-party: {', '.join(sorted(external))}")
    if not entries:
        entries = ["None (self-contained; standard library only)"]
    return [line for entry in entries for line in _wrap(f"- {entry}")]


def _dunder_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        is_all = any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets)
        if is_all and isinstance(value, ast.List | ast.Tuple):
            return [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def _output_lines(tree: ast.Module) -> list[str]:
    exported = _dunder_all(tree)
    items: list[str] = []
    defined: set[str] = set()
    for node in tree.body:
        if not isinstance(node, _DefNode):
            continue
        defined.add(node.name)
        public = node.name in exported if exported is not None else not node.name.startswith("_")
        if not public:
            continue
        label = node.name if isinstance(node, ast.ClassDef) else f"{node.name}()"
        doc = ast.get_docstring(node)
        summary = _prose_summary(doc) if doc else ""
        items.append(f"{label}: {summary}" if summary else label)
    reexported = [name for name in exported or [] if name not in defined]
    if reexported:
        items.append(f"Re-exports: {', '.join(reexported)}")
    if len(items) > _MAX_OUTPUT_ITEMS:
        items = [*items[:_MAX_OUTPUT_ITEMS], f"(+{len(items) - _MAX_OUTPUT_ITEMS} more public symbols)"]
    if not items:
        items = ["None (no public symbols)"]
    return [line for item in items for line in _wrap(f"- {item}")]


# ------------------------------------------------------------------- source rewriting


def _offset(source: str, lineno: int, byte_col: int) -> int:
    """Character offset of an ``ast`` position (1-based line, UTF-8 byte column)."""
    lines = source.split("\n")
    before = sum(len(line) + 1 for line in lines[: lineno - 1])
    return before + len(lines[lineno - 1].encode("utf-8")[:byte_col].decode("utf-8"))


def _literal_span(source: str, node: ast.Constant) -> tuple[int, int, str]:
    start = _offset(source, node.lineno, node.col_offset)
    end = _offset(source, node.end_lineno or node.lineno, node.end_col_offset or node.col_offset)
    body = source[start:end].lstrip("rRuU")
    delimiter = body[:3]
    if delimiter not in ('"""', "'''") or len(body) < 6 or not body.endswith(delimiter):
        raise HeaderError("module docstring is not a single triple-quoted literal")
    return start, end, delimiter


def _append_sections(source: str, node: ast.Constant, sections: str) -> str:
    _, end, delimiter = _literal_span(source, node)
    head = source[: end - 3].rstrip()
    return f"{head}\n\n{sections}\n{delimiter}{source[end:]}"


def _insert_docstring(source: str, node: ast.Constant | None, text: str) -> str:
    block = f'"""{text}\n"""'
    if node is not None:
        start, end, _ = _literal_span(source, node)
        return source[:start] + block + source[end:]
    lines = source.split("\n")
    keep = 0
    if lines and lines[0].startswith("#!"):
        keep = 1
    if keep < len(lines) and _CODING_RE.match(lines[keep]):
        keep += 1
    prefix = "\n".join(lines[:keep])
    tail = "\n".join(lines[keep:]).lstrip("\n")
    head = f"{prefix}\n" if prefix else ""
    return f"{head}{block}\n\n{tail}" if tail.strip() else f"{head}{block}\n"


def _fingerprint(tree: ast.Module) -> str:
    skip = 1 if _docstring_node(tree) is not None else 0
    return "\n".join(ast.dump(statement) for statement in tree.body[skip:])


def _verify(old_tree: ast.Module, new_source: str) -> None:
    """Prove the rewrite is docstring-only and warning-free before it is written."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            new_tree = ast.parse(new_source)
        except (SyntaxError, ValueError) as exc:
            raise HeaderError(f"rewrite would not compile cleanly: {exc}") from exc
    if _docstring_node(new_tree) is None or _fingerprint(new_tree) != _fingerprint(old_tree):
        raise HeaderError("rewrite would change more than the module docstring")
