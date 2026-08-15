"""
Regression tests: ExcelReadResult.row_numbers must record the original
1-based Excel row for each style_code's first occurrence.

Row 1 = the header row when a header is detected; data rows start at 2.
When no header is detected, row 1 is the first data row.
"""
import io
import pytest
import openpyxl

from psydox.batch.excel_reader import read_excel_bytes


def _make_excel(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestRowNumbers:
    def test_with_header_row(self):
        """Header in row 1; data starts at row 2."""
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1"],
            ["ABC001", "https://example.com/a.jpg"],
            ["ABC002", "https://example.com/b.jpg"],
        ])
        result = read_excel_bytes(data)
        assert result.ok
        assert result.row_numbers["ABC001"] == 2
        assert result.row_numbers["ABC002"] == 3

    def test_without_header_row(self):
        """No header detected; first data row is row 1."""
        data = _make_excel([
            ["PROD-X", "https://example.com/a.jpg"],
            ["PROD-Y", "https://example.com/b.jpg"],
        ])
        result = read_excel_bytes(data)
        assert result.ok
        # Row 1 = first data row (no header skipped)
        assert result.row_numbers["PROD-X"] == 1
        assert result.row_numbers["PROD-Y"] == 2

    def test_duplicate_style_keeps_first_row(self):
        """When the same style_code appears twice, row_number is the first occurrence."""
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1"],
            ["DUP001", "https://example.com/a.jpg"],
            ["DUP001", "https://example.com/b.jpg"],
        ])
        result = read_excel_bytes(data)
        assert result.ok
        assert result.row_numbers["DUP001"] == 2

    def test_blank_rows_skipped(self):
        """Blank rows between data rows must not shift the row numbering."""
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1"],
            ["FIRST", "https://example.com/a.jpg"],
            [None, None],
            ["THIRD", "https://example.com/c.jpg"],
        ])
        result = read_excel_bytes(data)
        assert result.ok
        assert result.row_numbers["FIRST"] == 2
        assert result.row_numbers["THIRD"] == 4

    def test_row_numbers_populated_for_all_styles(self):
        """Every style that makes it into the styles dict must have a row_number entry."""
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1"],
            ["A", "https://example.com/a.jpg"],
            ["B", "https://example.com/b.jpg"],
            ["C", "https://example.com/c.jpg"],
        ])
        result = read_excel_bytes(data)
        for code in result.styles:
            assert code in result.row_numbers, f"Missing row_number for style {code!r}"

    def test_row_numbers_not_in_result_for_skipped_styles(self):
        """Styles with no valid URLs are skipped — they shouldn't appear in row_numbers."""
        data = _make_excel([
            ["STYLE_CODE", "IMAGE1"],
            ["GOOD", "https://example.com/a.jpg"],
            ["BAD", "not-a-url"],
        ])
        result = read_excel_bytes(data)
        assert "GOOD" in result.row_numbers
        assert "BAD" not in result.styles
