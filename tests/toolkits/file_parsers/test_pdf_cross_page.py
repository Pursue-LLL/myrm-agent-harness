"""Unit tests for precision-first cross-page table stitching."""

from myrm_agent_harness.toolkits.file_parsers.base import PDFTable
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_cross_page import (
    stitch_cross_page_tables,
)

_PAGE_HEIGHT = 800.0


def _table(
    page: int,
    data: list[list[str]],
    *,
    bbox: tuple[float, float, float, float] | None,
    column_starts: tuple[float, ...] | None = None,
) -> PDFTable:
    return PDFTable(page_number=page, table_index=0, data=data, bbox=bbox, column_starts=column_starts)


def _heights(*pages: int) -> dict[int, float]:
    return {page: _PAGE_HEIGHT for page in pages}


class TestRepeatedHeaderMerge:
    """Boundary fragments with an identical header are merged."""

    def test_merges_and_drops_repeated_header(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"], ["乙", "200"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        stitched = stitch_cross_page_tables([first, second], _heights(5, 6))

        assert len(stitched) == 1
        assert stitched[0].data == [["项目", "金额"], ["甲", "100"], ["乙", "200"], ["丙", "300"]]
        assert stitched[0].page_number == 5
        assert stitched[0].page_range == (5, 6)

    def test_chains_across_three_pages(self):
        first = _table(2, [["列", "值"], ["a", "1"]], bbox=(60, 700, 540, 780))
        second = _table(3, [["列", "值"], ["b", "2"]], bbox=(60, 40, 540, 780))
        third = _table(4, [["列", "值"], ["c", "3"]], bbox=(60, 40, 540, 120))

        stitched = stitch_cross_page_tables([first, second, third], _heights(2, 3, 4))

        assert len(stitched) == 1
        assert stitched[0].page_range == (2, 4)
        assert [row[0] for row in stitched[0].data] == ["列", "a", "b", "c"]


class TestColumnSignatureMerge:
    """Header-less continuations merge only with layout evidence."""

    def test_merges_with_column_signature_and_cut_row(self):
        first = _table(
            5,
            [["项目", "数量", "金额"], ["甲", "1", ""]],
            bbox=(60, 700, 540, 780),
            column_starts=(60.0, 200.0, 360.0),
        )
        second = _table(
            6,
            [["乙", "2", "300"]],
            bbox=(60, 40, 540, 120),
            column_starts=(60.0, 200.0, 360.0),
        )

        stitched = stitch_cross_page_tables([first, second], _heights(5, 6))

        assert len(stitched) == 1
        assert stitched[0].data == [["项目", "数量", "金额"], ["甲", "1", ""], ["乙", "2", "300"]]

    def test_no_merge_without_cut_row_cue(self):
        first = _table(
            5,
            [["项目", "数量", "金额"], ["甲", "1", "100"]],
            bbox=(60, 700, 540, 780),
            column_starts=(60.0, 200.0, 360.0),
        )
        second = _table(
            6,
            [["乙", "2", "300"]],
            bbox=(60, 40, 540, 120),
            column_starts=(60.0, 200.0, 360.0),
        )

        stitched = stitch_cross_page_tables([first, second], _heights(5, 6))

        assert len(stitched) == 2

    def test_no_merge_without_column_signature(self):
        first = _table(5, [["项目", "数量"], ["甲", ""]], bbox=(60, 700, 540, 780))
        second = _table(6, [["乙", "2"]], bbox=(60, 40, 540, 120))

        stitched = stitch_cross_page_tables([first, second], _heights(5, 6))

        assert len(stitched) == 2


class TestMergeGuards:
    """Unrelated or malformed fragments must never be merged."""

    def test_no_merge_when_first_table_not_at_page_bottom(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 400, 540, 480))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_when_second_table_not_at_page_top(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 300, 540, 380))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_on_non_adjacent_pages(self):
        first = _table(3, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        second = _table(5, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(3, 5))) == 2

    def test_no_merge_with_different_headers(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["姓名", "部门"], ["丙", "采购"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_with_different_column_counts(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["项目", "金额", "备注"], ["丙", "300", ""]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_for_near_full_page_artifact(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(0, 5, 550, 790))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(0, 5, 550, 790))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_without_bbox(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=None)
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_no_merge_without_page_height(self):
        first = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], {})) == 2

    def test_single_row_fragment_not_merged(self):
        first = _table(5, [["项目", "金额"]], bbox=(60, 700, 540, 780))
        second = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 40, 540, 120))

        assert len(stitch_cross_page_tables([first, second], _heights(5, 6))) == 2

    def test_unrelated_second_table_on_same_page_not_merged(self):
        merged_pair = _table(5, [["项目", "金额"], ["甲", "100"]], bbox=(60, 700, 540, 780))
        continuation = _table(6, [["项目", "金额"], ["乙", "200"]], bbox=(60, 40, 540, 120))
        unrelated = _table(6, [["项目", "金额"], ["丙", "300"]], bbox=(60, 300, 540, 380))

        stitched = stitch_cross_page_tables([merged_pair, continuation, unrelated], _heights(5, 6))

        assert len(stitched) == 2
        assert stitched[0].page_range == (5, 6)
        assert stitched[1].data[-1] == ["丙", "300"]
