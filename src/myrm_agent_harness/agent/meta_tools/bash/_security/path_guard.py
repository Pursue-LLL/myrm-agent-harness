"""Path protection guard for bash commands.

[INPUT]
- core.security.path::is_sensitive_file, is_evidence_readonly_file (POS: single source of truth for sensitive-file and read-only-evidence rules, shared with the file tools)
- core.security.path.pattern::first_matching_pattern (POS: shared path-pattern matcher)
- agent.middlewares._session_context::get_protected_paths (POS: ContextVar for Goal-scoped protected patterns)
- utils.errors::ToolError (POS: Agent tool error with format_for_llm protocol)

[OUTPUT]
- check_sensitive_paths: Block commands touching credential paths, and writes to read-only evidence or Goal-protected paths.

[POS]
Path protection for the shell channel. Credential paths are refused for reads and
writes; evidence directories and the active Goal's protected paths are refused for
writes only, mirroring the ``VIEW`` bypass in the file-tool validators, so reading a
source file or a report stays possible. Write intent is derived from the command
itself (write commands, redirect targets, copy/sync destinations, tar direction,
output flags, script interpreters) rather than from a fixed verb list, because the
same verb reads in one position and writes in another. Inline ``sh -c`` / ``bash -c``
scripts are unwrapped and rescanned, and commit messages and ``echo``/``printf``
literals are stripped first, so neither a protected path hidden one quoting level
down nor prose that merely names a credential decides the outcome.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence

from myrm_agent_harness.agent.meta_tools.bash._security.shell_parse import extract_shell_c_payload
from myrm_agent_harness.core.security.path import is_evidence_readonly_file, is_sensitive_file
from myrm_agent_harness.core.security.path.pattern import first_matching_pattern

logger = logging.getLogger(__name__)


_SENSITIVE_PATH_RE = re.compile(
    r'(?:^|[\s"\'=/])(?:\.ssh|\.aws|\.npmrc|\.gnupg|\.docker|\.kube|\.bash_history|\.zsh_history|id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|etc/shadow|etc/passwd)(?:/|[\s"\'$]|$)',
    re.IGNORECASE,
)

# Shell metacharacters that end one command word. A path operand is delimited by
# one of these, so splitting on them yields the same words the shell would.
_SHELL_WORD_SEPARATORS = re.compile(r"[\s\"'|<>;()`&]")

# A word carrying a URI scheme names a remote resource, not a file on this
# machine, so its path component is out of scope for the local file rules.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

# ``sh -c "sh -c '...'"`` nests arbitrarily deep in principle; the cap keeps the
# unwrap loop bounded on a self-referential payload.
_MAX_NESTED_SHELL_DEPTH = 4

# Commands that can change a file. Only these make the immutable and
# Goal-scoped rules below apply; a command that merely names a protected path
# (``ls evidence/``, ``cat .env``) stays allowed, mirroring the ``VIEW`` bypass
# in the file-tool validators.
_WRITE_COMMANDS: frozenset[str] = frozenset({
    "cp", "dd", "install", "ln", "mv", "rm", "rmdir", "shred", "tee", "touch", "truncate",
})

# Copy/sync tools that treat their final operand as the destination. Their
# direction is unambiguous — a destination is written — so naming them here
# covers a directory target such as ``rsync -a dist/ evidence/`` without
# having to recognise every individual path.
_DESTINATION_COMMANDS: frozenset[str] = frozenset({
    "cp", "dd", "install", "ln", "mv", "rsync", "scp", "sftp", "smbclient",
})

# ``tar`` sub-commands that write into the archive tree. ``c``/``t`` only read
# the named paths, so a read-only ``tar czf out.tgz evidence/`` must stay
# allowed even though ``evidence/`` is immutable. Short flags bundle, so ``xf``
# and ``xzf`` carry the same operation as ``x``.
_TAR_WRITE_FLAGS: frozenset[str] = frozenset({"x", "r", "u", "a"})
_TAR_LONG_WRITE_FLAGS: frozenset[str] = frozenset({"--extract", "--append", "--update"})
_TAR_LONG_READ_FLAGS: frozenset[str] = frozenset({
    "--create", "--list", "--to-stdout", "--get", "--test", "--strip-components",
})

# Redirection and in-place-edit operators, which write without a command name.
_WRITE_REDIRECT = re.compile(r"(?:^|[^0-9<>])>{1,2}(?!&)")

# Interpreters whose own arguments decide whether a file changes.
_SCRIPT_INTERPRETERS: frozenset[str] = frozenset({
    "node", "perl", "php", "python", "python3", "ruby", "bash", "sh", "zsh",
})

# Download flags that name a local destination. A command carrying one writes a
# file, while the same command without it only streams to stdout, so uploads
# such as ``curl --data @evidence/x`` keep reading.
_OUTPUT_FLAG = re.compile(r"^(?:-o|--output|--output-document|--output-file)(?:=|$)")

_COMMIT_MESSAGE_PATTERN = re.compile(
    r'(?:^|[\s;&|])git\s+commit\s+(?:-[a-zA-Z]*m[a-zA-Z]*|--message(?:=|\s+))\s*(?:\'([^\']*)\'|"([^"]*)")',
    re.IGNORECASE,
)
_ECHO_PRINT_PATTERN = re.compile(
    r'(?:^|[\s;&|])(?:echo|printf)\s+(?:\'([^\']*)\'|"([^"]*)")',
    re.IGNORECASE,
)


def _strip_benign_text_literals_for_sensitive_check(command: str) -> str:
    """Strip commit message strings and echo print literals to prevent false alarms on commit texts."""
    cleaned = _COMMIT_MESSAGE_PATTERN.sub(" git commit ", command)
    cleaned = _ECHO_PRINT_PATTERN.sub(" echo ", cleaned)
    return cleaned


def _iter_command_words(command: str) -> Iterator[str]:
    """Yield each shell word of *command* that could name a filesystem path.

    Splits on shell metacharacters so that redirections (``>``, ``>>``) and
    pipes separate words the same way the shell does. Quoted spans keep their
    contents together, so a path written as ``"vault/secrets.json"`` survives
    as one word instead of being cut at the quote.
    """
    word: list[str] = []
    quote: str | None = None
    for char in command:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                word.append(char)
            continue
        if char in "\"'":
            quote = char
            continue
        if _SHELL_WORD_SEPARATORS.search(char):
            if word:
                yield "".join(word)
                word.clear()
            continue
        word.append(char)
    if word:
        yield "".join(word)


def _is_protected_path_word(word: str) -> bool:
    """Return True when *word* names a credential or key file on this machine.

    Path operands reach the file tools as plain strings, so the same matcher
    that guards ``file_write_tool`` also guards the shell. A word only counts
    when it looks like a path — a dot, a separator, or a leading ``~`` — which
    keeps ordinary arguments such as ``id_rsa_keygen`` out of the comparison.
    URI operands are skipped: ``https://host/config.json`` ends in a protected
    name but fetches a remote document rather than reading a local file.
    """
    if not word or word.startswith("-") or _URI_SCHEME.match(word):
        return False
    if not any(marker in word for marker in (".", "/", "~")):
        return False
    return is_sensitive_file(word.rstrip("/"))


def _is_tar_write(words: Sequence[str]) -> bool:
    """Return True when a ``tar`` invocation writes into the archive tree.

    Short flags bundle (``xzf`` carries the same operation as ``x``), so each
    flag cluster is scanned letter by letter. Legacy ``tar`` also accepts the
    cluster without a leading dash, so a bare word counts only when it is all
    letters — that keeps operands such as ``out.tgz`` out of the scan.
    ``-O`` / ``--to-stdout`` send the archive to standard output and therefore
    read rather than write.
    """
    for word in words[1:]:
        if word in _TAR_LONG_READ_FLAGS:
            return False
        if word in _TAR_LONG_WRITE_FLAGS:
            return True
        if word.startswith("--"):
            continue
        if word.startswith("-"):
            cluster = word[1:]
        elif word.isalpha():
            cluster = word
        else:
            continue
        if not cluster:
            continue
        if "O" in cluster:
            return False
        if set(cluster) & _TAR_WRITE_FLAGS:
            return True
    return False


def _is_write_command(script: str) -> bool:
    """Return True when *script* can modify a file on disk.

    Three shapes count: a command name that writes (``cp``, ``rm``, ``tee``, …),
    a redirection or in-place edit operator, and a copy/sync tool whose final
    operand is a destination. Anything else — ``ls``, ``cat``, ``grep``, and a
    read-only ``tar c`` — only reads, so the immutable-path rules do not apply.
    """
    words = list(_iter_command_words(script))
    if not words:
        return False
    if words[0] in _WRITE_COMMANDS or any(word in _WRITE_COMMANDS for word in words):
        return True
    if _WRITE_REDIRECT.search(script):
        return True
    # A script interpreter can write through any of the edits above
    # (``perl -pi -e``, ``sed -i``, ``python -c "open(...)"``), so treat the
    # interpreters themselves as write commands rather than trying to
    # recognise every flag spelling.
    if words[0] in _SCRIPT_INTERPRETERS:
        return True
    if any(_OUTPUT_FLAG.match(word) for word in words):
        return True
    if words[0] == "tar":
        return _is_tar_write(words)
    if words[0] in _DESTINATION_COMMANDS:
        return True
    return any(flag in script for flag in ("-i", "--in-place"))


def _operand_candidates(word: str) -> Iterator[str]:
    """Yield the path-like operands carried by *word*.

    A path operand reaches a command either bare (``cp a evidence/x``), glued
    to an assignment (``of=evidence/x``) or attached to a flag
    (``--output=evidence/x``), so the value after the first ``=`` is always
    checked alongside the whole word.
    """
    if not word or _URI_SCHEME.match(word):
        return
    if not word.startswith("-") and any(m in word for m in (".", "/", "~")):
        yield word
    if "=" in word:
        _, _, value = word.partition("=")
        if value and not _URI_SCHEME.match(value) and any(m in value for m in (".", "/", "~")):
            yield value


def _matches_immutable_path(word: str) -> bool:
    """Return True when *word* names an evidence file or a Goal-protected path.

    Evidence directories are tested with the shared predicate so the shell and
    the file tools agree down to the bare-directory form; Goal patterns are
    tested with the raw operand so a relative pattern keeps its own shape.
    """
    from myrm_agent_harness.agent.middlewares._session_context import get_protected_paths

    if is_evidence_readonly_file(word):
        return True
    return first_matching_pattern(word, get_protected_paths()) is not None


def _find_sensitive_path(command: str) -> str | None:
    """Return the first sensitive path *command* touches, else None.

    Inline ``sh -c`` / ``bash -c`` scripts are unwrapped and rescanned so a
    protected path cannot be hidden one quoting level down. The bare-credential
    alternation is kept as a second opinion: it recognises filenames such as
    ``id_rsa`` that carry no dot or separator, which the path-shaped test above
    cannot see.
    """
    scripts = [command]
    for _ in range(_MAX_NESTED_SHELL_DEPTH):
        nested = [payload for payload in map(extract_shell_c_payload, scripts) if payload]
        if not nested:
            break
        scripts.extend(nested)

    for script in scripts:
        for word in _iter_command_words(script):
            if _is_protected_path_word(word):
                return word
        if not _is_write_command(script):
            continue
        for word in _iter_command_words(script):
            for operand in _operand_candidates(word):
                if _matches_immutable_path(operand):
                    return operand

    match = _SENSITIVE_PATH_RE.search(command)
    return match.group(0).strip(" \"'=/") if match else None


def check_sensitive_paths(command: str) -> None:
    """Block commands that write to protected, immutable, or Goal-scoped files.

    Credentials are refused whether the command reads or writes them. Evidence
    directories and the active Goal's protected paths are refused for writes
    only, mirroring the ``VIEW`` bypass in the file-tool validators, so reading
    a source file or a report stays possible. Inline ``sh -c`` / ``bash -c``
    scripts are unwrapped and rescanned, and commit messages and
    ``echo``/``printf`` literals are stripped first, so neither a protected path
    hidden one quoting level down nor prose that merely names a credential
    decides the outcome.

    Raises:
        ToolError: If the command would touch a protected file.
    """
    from myrm_agent_harness.utils.errors import ToolError

    eval_cmd = _strip_benign_text_literals_for_sensitive_check(command)

    if sensitive_path := _find_sensitive_path(eval_cmd):
        logger.warning(f" Sensitive path access detected: {command[:100]}")
        raise ToolError(
            f"Command blocked (security): '{sensitive_path}' is a protected file.",
            user_hint=(
                f"Do not route around this restriction. Continue without {sensitive_path}, "
                f"or tell the user which file you could not use."
            ),
        )
