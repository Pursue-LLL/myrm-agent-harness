"""Unit tests for heading fusion and in-place insertion."""

from myrm_agent_harness.toolkits.file_parsers.base import PDFHeading
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_headings import (
    build_numbering_cues,
    fuse_headings,
    insert_headings_into_page_text,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_numbering import NumberingHeading


class TestFusion:
    """Numbering and font candidates merge without duplication."""

    def test_numbering_level_wins_on_collision(self):
        numbering = [NumberingHeading(page_num=1, level=2, title="1.1 概述", line_index=2)]
        font = [PDFHeading(level=1, title="1.1 概述", page_num=1)]

        fused = fuse_headings(numbering, font)

        assert fused == [PDFHeading(level=2, title="1.1 概述", page_num=1)]

    def test_distinct_sources_are_kept(self):
        numbering = [NumberingHeading(page_num=1, level=1, title="1.1 概述", line_index=0)]
        font = [PDFHeading(level=1, title="摘要", page_num=1)]

        fused = fuse_headings(numbering, font)

        assert [h.title for h in fused] == ["1.1 概述", "摘要"]

    def test_whitespace_difference_deduplicates(self):
        numbering = [NumberingHeading(page_num=1, level=1, title="1.1 概述", line_index=0)]
        font = [PDFHeading(level=1, title="1.1  概述", page_num=1)]

        assert len(fuse_headings(numbering, font)) == 1

    def test_build_numbering_cues_groups_by_page(self):
        font = [
            PDFHeading(level=1, title="2. 模式片段：行为约束", page_num=1),
            PDFHeading(level=1, title="摘要", page_num=2),
        ]

        cues = build_numbering_cues(font)

        assert cues[1] == frozenset({"2.模式片段：行为约束"})
        assert cues[2] == frozenset({"摘要"})


class TestInlineInsertion:
    """Headings are placed at their original line; unmatched ones hoist."""

    def test_heading_inserted_at_original_line(self):
        page_text = "第一段正文内容\n1.1 概述与范围\n第二段正文内容"

        result = insert_headings_into_page_text(page_text, [PDFHeading(level=2, title="1.1 概述与范围", page_num=1)])

        assert result == "第一段正文内容\n## 1.1 概述与范围\n第二段正文内容"

    def test_unmatched_heading_hoisted_to_top(self):
        page_text = "正文内容"

        result = insert_headings_into_page_text(page_text, [PDFHeading(level=1, title="Chapter 1", page_num=1)])

        assert result == "# Chapter 1\n正文内容"

    def test_prefix_match_for_bookmark_titles(self):
        page_text = "1.1 第一环：你的话加上它的记忆，一起出发\n正文"

        result = insert_headings_into_page_text(page_text, [PDFHeading(level=2, title="1.1 第一环", page_num=1)])

        assert result.startswith("## 1.1 第一环：你的话加上它的记忆，一起出发\n")

    def test_already_prefixed_line_is_not_duplicated(self):
        page_text = "# 已有标题\n正文"

        result = insert_headings_into_page_text(page_text, [PDFHeading(level=1, title="已有标题", page_num=1)])

        assert result == "# 已有标题\n正文"

    def test_empty_page_text_returns_hoisted_headings(self):
        result = insert_headings_into_page_text("", [PDFHeading(level=1, title="摘要", page_num=1)])

        assert result == "# 摘要"

    def test_no_headings_returns_text_unchanged(self):
        assert insert_headings_into_page_text("正文", []) == "正文"
