"""Unit tests for clause-numbering heading detection guards and level mapping."""

from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_numbering import (
    NumberingHeading,
    NumberingHeadingConfig,
    detect_numbering_headings,
    filter_repeated_titles,
    normalize_heading_title,
)


def _detect(text: str, **kwargs):
    return detect_numbering_headings([text], **kwargs)


class TestFamilyRecognition:
    """Supported numbering families map to hierarchy levels."""

    def test_chinese_chapter_section_article(self):
        text = "第一章 总则\n第一节 范围\n第一条 目的\n正文内容"

        hits = _detect(text)

        assert [(h.level, h.title) for h in hits] == [
            (1, "第一章 总则"),
            (2, "第一节 范围"),
            (3, "第一条 目的"),
        ]
        assert [h.line_index for h in hits] == [0, 1, 2]

    def test_whitespace_tolerant_markers(self):
        hits = _detect("第 3 章 全景：文件与状态\n第 4 条 交付")

        assert [(h.level, h.title) for h in hits] == [(1, "第 3 章 全景：文件与状态"), (2, "第 4 条 交付")]

    def test_chinese_ordinal_and_parenthesised_levels(self):
        hits = _detect("一、总体要求\n（一）设计原则\n1. 实现细节\n① 注意事项")

        assert [(h.level, h.title) for h in hits] == [
            (1, "一、总体要求"),
            (2, "（一）设计原则"),
            (3, "1. 实现细节"),
            (4, "① 注意事项"),
        ]

    def test_multi_level_numeric_root_and_children(self):
        hits = _detect("2.1 项目背景\n2.2 建设目标\n2.2.1 分目标\n2.3 实施路径")

        assert [(h.level, h.title) for h in hits] == [
            (1, "2.1 项目背景"),
            (1, "2.2 建设目标"),
            (2, "2.2.1 分目标"),
            (1, "2.3 实施路径"),
        ]

    def test_runon_cjk_title(self):
        hits = _detect("3.1概述与范围\n3.2方法论")

        assert [(h.level, h.title) for h in hits] == [(1, "3.1概述与范围"), (1, "3.2方法论")]


class TestPrecisionGuards:
    """False-positive-prone lines must be rejected."""

    def test_toc_dot_leaders_rejected(self):
        text = "1.1 第一环：出发············6\n1.2 第二环：行动....7\n一、总则"

        hits = _detect(text)

        assert [(h.title, h.level) for h in hits] == [("一、总则", 1)]

    def test_prose_sentence_rejected(self):
        text = "1. 终端硬件链订单能见度较上周改善，但海外库存去化仍是变量。\n2. 云设备链资本开支节奏尚不稳定。"

        assert _detect(text) == []

    def test_clause_reference_prose_rejected(self):
        text = "第一条读的是你的用户级长期记忆；第二条列出插件市场\n第二条 保密义务"

        hits = _detect(text)

        assert [(h.title, h.level) for h in hits] == [("第二条 保密义务", 1)]

    def test_year_like_tokens_rejected(self):
        text = "2024.05 月度报告\n2026年第一季度回顾\n1.1 正式章节"

        hits = _detect(text)

        assert [(h.title, h.level) for h in hits] == [("1.1 正式章节", 1)]

    def test_float_like_tokens_rejected(self):
        text = "3.14159 是圆周率近似值\n1.1 有效章节"

        hits = _detect(text)

        assert [(h.title, h.level) for h in hits] == [("1.1 有效章节", 1)]

    def test_orphan_child_depth_rejected(self):
        text = "1.1.1 没有父级的孤儿小节\n1.1 一级小节"

        hits = _detect(text)

        assert [(h.title, h.level) for h in hits] == [("1.1 一级小节", 1)]

    def test_long_line_rejected(self):
        line = "1. " + "内容" * 40

        assert _detect(line) == []

    def test_single_level_only_document_dropped(self):
        text = "1. 第一个要点\n2. 第二个要点\n3. 第三个要点"

        assert _detect(text) == []

    def test_per_page_cap(self):
        text = "\n".join(f"{idx}.1 小节{idx}" for idx in range(1, 11))

        hits = _detect(text)

        assert len(hits) == NumberingHeadingConfig().max_headings_per_page

    def test_single_value_restart_rejected(self):
        text = "5. 验收标准\n3. 乱序条目\n一、总则"

        hits = _detect(text)

        assert [h.title for h in hits] == ["5. 验收标准", "一、总则"]


class TestSingleLevelColonPolicy:
    """Colon-tailed list descriptions need a visual cue to become headings."""

    def test_colon_list_item_rejected(self):
        text = "2. 模式片段：按当前交互模式条件拼入的行为约束\n1.1 结构章节"

        hits = _detect(text)

        assert [h.title for h in hits] == ["1.1 结构章节"]

    def test_colon_item_accepted_with_visual_cue(self):
        line = "2. 模式片段：按当前交互模式条件拼入的行为约束"
        cues = {1: frozenset({normalize_heading_title(line)})}

        hits = detect_numbering_headings([line + "\n一、总则"], cue_titles=cues)

        assert [h.title for h in hits] == ["2. 模式片段：按当前交互模式条件拼入的行为约束", "一、总则"]


class TestRepeatedTitleFilter:
    """Running headers/footers must not become headings."""

    def test_running_title_filtered(self):
        headings = [
            NumberingHeading(page_num=page, level=1, title="第 3 章 全景", line_index=0) for page in range(1, 11)
        ]
        headings.append(NumberingHeading(page_num=2, level=2, title="3.1 小节", line_index=1))

        filtered = filter_repeated_titles(headings, page_count=10)

        assert [h.title for h in filtered] == ["3.1 小节"]

    def test_short_document_never_filtered(self):
        headings = [NumberingHeading(page_num=1, level=1, title="标题", line_index=0)]

        assert filter_repeated_titles(headings, page_count=2) == headings
