"""Tests for the wiki link syntax SSOT (core.link_extraction)."""

import pytest

from myrm_agent_harness.toolkits.wiki.core.link_extraction import (
    extract_markdown_link_targets,
    extract_wikilink_targets,
    find_wikilinks,
    is_external_link,
    mask_code,
    normalize_wikilink_target,
    parse_wikilink,
    protect_code,
)


def test_normalize_wikilink_target_strips_alias_anchor_and_extension() -> None:
    assert normalize_wikilink_target("Foo/Bar|shown") == "Foo/Bar"
    assert normalize_wikilink_target("Foo#Heading") == "Foo"
    assert normalize_wikilink_target("Foo/Bar.md") == "Foo/Bar"
    assert normalize_wikilink_target("Foo/Bar.MD#Heading|shown") == "Foo/Bar"


def test_parse_wikilink_splits_label_before_heading() -> None:
    parts = parse_wikilink(" Note #Head|label#x ")
    assert (parts.note, parts.fragment, parts.label) == ("Note", "Head", "label#x ")
    bare = parse_wikilink("Note")
    assert (bare.note, bare.fragment, bare.label) == ("Note", None, None)


class TestCodeIsNeverALink:
    @pytest.mark.parametrize(
        "content",
        [
            "```bash\nif [[ -f x ]]; then\n[[Hidden]]\n```\n",
            "~~~\n[[Hidden]]\n~~~\n",
            "````md\n```bash\n[[Hidden]]\n```\n[[AlsoHidden]]\n````\n",
            "1. step\n    ```bash\n    [[Hidden]]\n    ```\n",
            "```\n[[NeverClosed]]\n[[Hidden]]\n",
            "`[[Hidden]]` and ``[[Hidden2]]``",
            "Code: ```\n[[Hidden]]\n``` and `[[Hidden2]]` inline.",
            "`a\n[[Hidden]]\nb`",
        ],
    )
    def test_links_inside_code_are_ignored(self, content: str) -> None:
        assert extract_wikilink_targets(content) == ()

    def test_links_around_code_are_kept(self) -> None:
        content = "[[Before]]\n```bash\n[[Hidden]]\n```\n[[After]] `x` [[Last]]\n"
        assert extract_wikilink_targets(content) == ("Before", "After", "Last")

    def test_markdown_links_inside_code_are_ignored(self) -> None:
        assert extract_markdown_link_targets("```\n[x](hidden.md)\n```\n`[y](hidden.md)`\n") == ()

    def test_unmatched_backtick_does_not_swallow_the_page(self) -> None:
        assert extract_wikilink_targets("it`s fine [[Real]] done") == ("Real",)

    def test_span_never_crosses_a_blank_line(self) -> None:
        assert extract_wikilink_targets("stray ` tick\n\n[[Real]]\n\nother ` tick") == ("Real",)

    def test_fence_opener_with_backtick_in_info_string_is_not_a_fence(self) -> None:
        assert extract_wikilink_targets("``` has `tick`\n[[Real]]\n") == ("Real",)

    def test_link_label_may_wrap_inline_code(self) -> None:
        assert extract_wikilink_targets("[[Page|see `x[0]`]]") == ("Page",)
        assert extract_markdown_link_targets("[`list[int]`](types.md)") == ("types.md",)

    def test_target_made_of_code_is_not_a_page(self) -> None:
        assert extract_wikilink_targets("[[`x`]]") == ()
        assert extract_markdown_link_targets("[a](`b`.md)") == ()


def test_protect_code_round_trips() -> None:
    content = "pre `a` mid\n```py\nfenced [[x]]\n```\npost"
    masked, restore = protect_code(content)
    assert "fenced" not in masked
    assert restore(masked) == content
    assert mask_code("no code here [[A]]") == "no code here [[A]]"


class TestWikilinkTargets:
    def test_targets_are_distinct_normalized_and_ordered(self) -> None:
        content = "[[Foo#Head|Label]] [[Bar.md]] [[Foo]] [[ Spaced ]]"
        assert extract_wikilink_targets(content) == ("Foo", "Bar", "Spaced")

    def test_non_page_targets_are_dropped(self) -> None:
        content = "[[#Same]] [[https://x.io]] [[system:note]] [[ ]] [[httpx client]]"
        assert extract_wikilink_targets(content) == ("httpx client",)

    def test_wikilink_must_stay_on_one_line(self) -> None:
        assert extract_wikilink_targets("stray [[ open\nclose ]] [[Real]]") == ("Real",)

    def test_find_wikilinks_keeps_source_text_and_label(self) -> None:
        found = find_wikilinks("see [[Page#Part|the `page`]] now")
        assert [raw for raw, _ in found] == ["[[Page#Part|the `page`]]"]
        parts = found[0][1]
        assert (parts.note, parts.fragment, parts.label) == ("Page", "Part", "the `page`")


class TestMarkdownLinkTargets:
    def test_external_links_and_anchors_are_not_vault_paths(self) -> None:
        content = "[a](#top) [b](mailto:x@y.co) [c](https://a.b/c.md) [d](//cdn/x.md) [e](tel:123)"
        assert extract_markdown_link_targets(content) == ()

    def test_fragment_is_stripped_and_targets_are_distinct(self) -> None:
        content = "[a](other.md#part) [b](other.md) [c](../x.md) [d](http-guide.md)"
        assert extract_markdown_link_targets(content) == ("other.md", "../x.md", "http-guide.md")

    @pytest.mark.parametrize(
        ("url", "external"),
        [("https://a.b", True), ("mailto:a@b.co", True), ("#top", True), ("//cdn/x", True), ("page.md", False)],
    )
    def test_is_external_link(self, url: str, external: bool) -> None:
        assert is_external_link(url) is external
