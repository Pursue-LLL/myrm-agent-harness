"""Tests for the shared shell command lexer: one reading of where commands end and what their words are."""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.shell_command_lexer import (
    UNTERMINATED,
    _scan_command_spans,
    _scan_words,
    has_word_expansion,
    iter_syntax_chars,
    shell_words,
    split_command_spans,
    strip_comments,
)


def commands(text: str) -> list[str]:
    """The text of every command span, as the approval card would highlight it."""
    return [text[start:end] for start, end in split_command_spans(text)]


class TestSplitCommandSpans:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ls", ["ls"]),
            ("ls | grep x", ["ls", "grep x"]),
            ("a; b", ["a", "b"]),
            ("a && b", ["a", "b"]),
            ("a || b", ["a", "b"]),
            ("a & b", ["a", "b"]),
            ("a |& b", ["a", "b"]),
            ("a;b|c&&d||e", ["a", "b", "c", "d", "e"]),
        ],
    )
    def test_operators_separate_commands(self, text: str, expected: list[str]) -> None:
        assert commands(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ls\nrm x", ["ls", "rm x"]),
            ("ls\r\nrm x", ["ls", "rm x"]),
            ("ls\r\rrm x", ["ls", "rm x"]),
            ("\n\nls\n\n\nrm x\n\n", ["ls", "rm x"]),
            ("ls\n# a note\nrm x", ["ls", "rm x"]),
            ("ls # a note\nrm x", ["ls # a note", "rm x"]),
        ],
    )
    def test_line_breaks_separate_commands(self, text: str, expected: list[str]) -> None:
        assert commands(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "echo 'a; b | c && d'",
            'echo "a; b | c && d"',
            "echo a\\; b",
            'echo "say \\"hi\\"; x"',
            "echo $'it\\'s; x'",
            "ls \\\n -la",
            "echo a#b",
            "echo a # b; c && d",
            "ls 2>&1",
            "ls &> out.txt",
            "ls >&2",
            "ls <&0",
        ],
    )
    def test_single_command(self, text: str) -> None:
        assert commands(text) == [text]

    def test_comment_starts_only_at_the_beginning_of_a_word(self) -> None:
        assert commands("echo a#b && rm x") == ["echo a#b", "rm x"]
        assert commands("echo a ;# note\nrm x") == ["echo a", "rm x"]

    def test_spans_index_the_original_text_without_surrounding_blanks(self) -> None:
        text = "  ls  |  wc -l  \n  rm x  "
        assert split_command_spans(text) == [(2, 4), (9, 14), (19, 23)]

    def test_operator_without_a_command_on_one_side_yields_an_empty_span(self) -> None:
        assert split_command_spans("ls ;") == [(0, 2), (4, 4)]
        assert split_command_spans("ls |  | wc") == [(0, 2), (6, 6), (8, 10)]
        assert split_command_spans("; ls") == [(0, 0), (2, 4)]

    def test_blank_and_comment_only_text_has_no_commands(self) -> None:
        assert split_command_spans("") == []
        assert split_command_spans(" \n\t\n ") == []
        assert split_command_spans("# nothing here") == []

    def test_unterminated_quote_stays_one_span(self) -> None:
        assert commands('echo "a; rm x') == ['echo "a; rm x']

    def test_ansi_c_quote_hides_an_escaped_quote_from_the_scanner(self) -> None:
        """``$'a\\'b'`` is one word in bash; reading ``\\'`` as the end of the quote would swap quoted and bare text."""
        text = "echo $'a\\'b' ; touch MARK ; echo 'c' 'd'"
        assert commands(text) == ["echo $'a\\'b'", "touch MARK", "echo 'c' 'd'"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # ``$$`` is the process id: the quote after an even number of dollars is a plain one, where ``\`` is literal
            # and the quote ends, so the canary on the next line is a command of its own.
            ("echo a$$'\\'\ntouch MARK", ["echo a$$'\\'", "touch MARK"]),
            ("echo a$$$$'\\'\ntouch MARK", ["echo a$$$$'\\'", "touch MARK"]),
            # After an odd number of dollars the last one opens an ANSI-C quote that ``\'`` does not close.
            ("echo a$'\\''\ntouch MARK", ["echo a$'\\''", "touch MARK"]),
            ("echo a$$$'\\''\ntouch MARK", ["echo a$$$'\\''", "touch MARK"]),
        ],
    )
    def test_only_a_lone_dollar_makes_the_next_quote_ansi_c(self, text: str, expected: list[str]) -> None:
        assert commands(text) == expected


class TestShellWords:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ls -la /tmp", ["ls", "-la", "/tmp"]),
            ('rg "--pre" x', ["rg", "--pre", "x"]),
            ("rg '--pre' x", ["rg", "--pre", "x"]),
            ('rg --p"re" x', ["rg", "--pre", "x"]),
            ("rg --p\\re x", ["rg", "--pre", "x"]),
            ("echo 'a b' c\\ d", ["echo", "a b", "c d"]),
            ('echo ""', ["echo", ""]),
            ('echo "a\\"b"', ["echo", 'a"b']),
            ('echo "a\\nb"', ["echo", "a\\nb"]),
            ("echo 'a\\nb'", ["echo", "a\\nb"]),
            ("ls # a note", ["ls"]),
            ("echo a#b", ["echo", "a#b"]),
            ("ec\\\nho hi", ["echo", "hi"]),
            ("  ", []),
        ],
    )
    def test_resolves_quotes_escapes_and_comments(self, text: str, expected: list[str]) -> None:
        assert shell_words(text) == expected

    @pytest.mark.parametrize("text", ['echo "unterminated', "echo 'unterminated", "echo trailing\\"])
    def test_unparseable_text_is_none(self, text: str) -> None:
        assert shell_words(text) is None


class TestHasWordExpansion:
    @pytest.mark.parametrize("text", ["ls $HOME", "ls ${HOME}", "ls `pwd`", "rg {--pre,x}", 'ls "$HOME"', "ls $'a'"])
    def test_expansion_can_rewrite_the_words(self, text: str) -> None:
        assert has_word_expansion(text) is True

    @pytest.mark.parametrize("text", ["ls", "ls '$HOME'", 'ls "{a,b}"', "ls \\{a\\}", "ls \\$HOME", "ls # $HOME"])
    def test_quoted_escaped_or_commented_text_is_literal(self, text: str) -> None:
        assert has_word_expansion(text) is False

    def test_unparseable_text_counts_as_expanding(self) -> None:
        assert has_word_expansion('ls "unterminated') is True


class TestStripComments:
    def test_comments_and_continuations_are_removed(self) -> None:
        assert strip_comments("a # note\nb") == "a \nb"
        assert strip_comments("ls;#c") == "ls;"
        assert strip_comments("# only a comment") == ""
        assert strip_comments("ec\\\nho hi") == "echo hi"

    def test_hash_inside_a_word_is_kept(self) -> None:
        assert strip_comments("echo a#b") == "echo a#b"

    def test_quoted_text_is_never_altered(self) -> None:
        for text in ['echo "a\nb"', "echo 'a # b' \"c # d\"", "echo 'x\\\ny'"]:
            assert strip_comments(text) == text


class TestIterSyntaxChars:
    def test_quoted_escaped_and_commented_characters_are_not_syntax(self) -> None:
        text = "a;'b;c'\\;d # e;f"
        assert [index for index, char in iter_syntax_chars(text) if char == ";"] == [1]

    def test_dollar_and_backtick_stay_syntax_inside_double_quotes(self) -> None:
        text = "echo \"$X `y` 'z'\" '$W'"
        assert [char for _, char in iter_syntax_chars(text) if char in "$`"] == ["$", "`", "`"]

    def test_unterminated_text_yields_the_sentinel_last(self) -> None:
        assert list(iter_syntax_chars('a "b'))[-1][1] == UNTERMINATED
        assert list(iter_syntax_chars("a\\"))[-1][1] == UNTERMINATED


# Fragments for random command lines: quotes, escapes, comments, every separator and redirect, ANSI-C quotes.
_ATOMS = [
    *["true", "a", " ", " ", "'", '"', "\\", "#", ";", "&&", "||", "|", "\n", "x", "-n", "&"],
    *[">&2", "2>&1", "&>/dev/null", ">/dev/null", "|&", "\n\n", "$", "$$", "$'", '$"', "\\'"],
]
# Fragments of a single command without operators, redirects or expansions: its words can be compared with bash's.
_WORD_ATOMS = ["true", "a", " ", " ", "'", '"', "\\", "#", "x", "-n", "--pre", "a b"]
_LEADING_REDIRECT_PREFIXES = ("&>", "2>", "1>", ">", "<")


_FAST_PATH_ALPHABET = (
    *"ab-x= \t\n\r;&|'\"\\#$`{}()<>",
    "\\\n",
    "$'",
    "&&",
    "||",
    "2>&1",
    " ls ",
)
_FAST_PATH_RNG = random.Random(20261017)
_FAST_PATH_SAMPLES = [
    "".join(_FAST_PATH_RNG.choice(_FAST_PATH_ALPHABET) for _ in range(_FAST_PATH_RNG.randint(0, 12)))
    for _ in range(6000)
]


class TestPlainCommandFastPaths:
    """Plain commands skip the character scan; the shortcut must never change an answer."""

    def test_shell_words_agree_with_the_scan(self) -> None:
        assert [shell_words(text) for text in _FAST_PATH_SAMPLES] == [_scan_words(text) for text in _FAST_PATH_SAMPLES]

    def test_command_spans_agree_with_the_scan(self) -> None:
        assert [split_command_spans(text) for text in _FAST_PATH_SAMPLES] == [
            _scan_command_spans(text) for text in _FAST_PATH_SAMPLES
        ]

    def test_expansion_check_agrees_with_the_syntax_characters(self) -> None:
        reference = [
            any(char in "${`" + UNTERMINATED for _, char in iter_syntax_chars(text)) for text in _FAST_PATH_SAMPLES
        ]
        assert [has_word_expansion(text) for text in _FAST_PATH_SAMPLES] == reference

    def test_text_without_comments_or_continuations_is_returned_as_is(self) -> None:
        plain = [text for text in _FAST_PATH_SAMPLES if "#" not in text and "\\" not in text]
        assert plain
        assert all(strip_comments(text) == text for text in plain)

    def test_the_samples_reach_both_the_shortcut_and_the_scan(self) -> None:
        shortcut = [text for text in _FAST_PATH_SAMPLES if not any(char in text for char in "\\'\"#$`{;&|\n\r")]
        assert 50 < len(shortcut) < len(_FAST_PATH_SAMPLES)


@pytest.mark.skipif(shutil.which("bash") is None, reason="differential test needs bash")
class TestAgreesWithBash:
    """The lexer must expose every command bash really runs, and resolve words the way bash does."""

    @staticmethod
    def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd)}
        return subprocess.run(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False
        )

    def test_no_command_hides_inside_a_quote_or_comment(self, tmp_path: Path) -> None:
        rng = random.Random(1017)
        marker = tmp_path / "MARK"
        executed = 0
        for _ in range(140):
            prefix = "".join(rng.choice(_ATOMS) for _ in range(rng.randint(0, 9)))
            script = prefix + "\ntouch MARK"
            marker.unlink(missing_ok=True)
            self._run(["bash", "--noprofile", "--norc", "-c", script], tmp_path)
            if not marker.exists():
                continue
            executed += 1
            first_words = []
            for start, end in split_command_spans(script):
                words = shell_words(script[start:end]) or []
                while words and words[0].startswith(_LEADING_REDIRECT_PREFIXES):
                    words = words[1:]
                first_words.append(words[:1])
            assert ["touch"] in first_words, f"bash ran the canary but the lexer hid it: {script!r}"
        assert executed > 30  # the generator must reach the canary often enough to mean something

    def test_words_match_what_bash_passes_on(self, tmp_path: Path) -> None:
        rng = random.Random(2026)
        compared = 0
        for _ in range(140):
            text = "".join(rng.choice(_WORD_ATOMS) for _ in range(rng.randint(1, 8)))
            if not text.strip():
                continue
            ran = self._run(["bash", "--noprofile", "--norc", "+B", "-f", "-c", "printf '%s\\0' " + text], tmp_path)
            if ran.returncode != 0 or text.endswith("\\"):
                continue
            words = ran.stdout.decode().split("\0")[:-1]
            expected = [] if words == [""] and shell_words(text) == [] else words
            assert shell_words(text) == expected, f"words differ for {text!r}"
            compared += 1
        assert compared > 30
