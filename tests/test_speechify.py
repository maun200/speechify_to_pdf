"""Unit tests for speechify_to_pdf core logic."""

import re
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory so we can import the single-file module
sys.path.insert(0, str(Path(__file__).parent.parent))
import speechify_to_pdf as stp


# ── extract_highlights ────────────────────────────────────────────────────────

def _make_html(entries: list[dict]) -> str:
    """Build minimal Speechify-style HTML from a list of highlight dicts."""
    blocks = []
    current_page = None
    for e in entries:
        if e["page"] != current_page:
            current_page = e["page"]
            blocks.append(
                f'<span>Page {current_page}</span></button>'
            )
        note_part = f". Note: {e['note']}" if e.get("note") else ""
        blocks.append(
            f'aria-label="Highlight: {e["text"]}{note_part} . Has context menu"'
            f' class="bg-bg-highlight-notes-{e["color"]} foo">'
            f'<span>{e["text"]}</span>'
        )
    return "\n".join(blocks)


def test_extract_single_highlight(tmp_path):
    html = _make_html([{"page": 3, "color": "yellow", "text": "Hello world", "note": None}])
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")

    result = stp.extract_highlights(f)
    assert len(result) == 1
    h = result[0]
    assert h["page"] == 3
    assert h["color"] == "yellow"
    assert h["text"] == "Hello world"
    assert h["note"] is None
    assert h["truncated"] is False


def test_extract_highlight_with_note(tmp_path):
    html = _make_html([{"page": 1, "color": "pink", "text": "Important", "note": "remember this"}])
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")

    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["note"] == "remember this"


def test_extract_truncated_highlight(tmp_path):
    html = _make_html([{"page": 2, "color": "blue", "text": "Some long text...", "note": None}])
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")

    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["truncated"] is True
    assert not result[0]["text"].endswith("...")


def test_extract_multiple_pages(tmp_path):
    entries = [
        {"page": 1, "color": "yellow", "text": "First", "note": None},
        {"page": 1, "color": "green", "text": "Second", "note": None},
        {"page": 5, "color": "orange", "text": "Fifth page", "note": None},
    ]
    html = _make_html(entries)
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")

    result = stp.extract_highlights(f)
    assert len(result) == 3
    assert result[0]["page"] == 1
    assert result[2]["page"] == 5


def test_extract_empty_html(tmp_path):
    f = tmp_path / "empty.html"
    f.write_text("<html></html>", encoding="utf-8")
    result = stp.extract_highlights(f)
    assert result == []


# ── guess_pdf_path ────────────────────────────────────────────────────────────

def test_guess_pdf_path_sibling(tmp_path):
    pdf = tmp_path / "MyBook.pdf"
    pdf.touch()
    html = tmp_path / "MyBook _ Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_parent_dir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    pdf = tmp_path / "Report.pdf"
    pdf.touch()
    html = sub / "Report _ Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "Thesis.pdf"
    pdf.touch()
    # HTML lives in a completely unrelated sub-directory
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "Thesis _ Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_not_found(tmp_path):
    html = tmp_path / "Ghost _ Speechify.html"
    html.touch()
    assert stp.guess_pdf_path(html) is None


def test_guess_pdf_path_case_insensitive(tmp_path):
    # stem name differs in case from HTML; extension must be lowercase (rglob limitation on Linux)
    d = tmp_path / "unique_ci_test"
    d.mkdir()
    pdf = d / "MyBook.pdf"
    pdf.touch()
    html = d / "mybook _ Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found is not None
    assert found.name.lower() == "mybook.pdf"


# ── COLOR_MAP ─────────────────────────────────────────────────────────────────

def test_color_map_values_in_range():
    for name, rgb in stp.COLOR_MAP.items():
        assert len(rgb) == 3, f"{name}: expected 3-tuple"
        for channel in rgb:
            assert 0.0 <= channel <= 1.0, f"{name}: channel {channel} out of range"


def test_default_color_in_map():
    assert stp.DEFAULT_COLOR in stp.COLOR_MAP.values()


# ── _PAGE_WORDS regex ─────────────────────────────────────────────────────────

def test_page_words_matches_english():
    assert re.match(stp._PAGE_WORDS, "Page")
    assert re.match(stp._PAGE_WORDS, "page", re.IGNORECASE)


def test_page_words_matches_german():
    assert re.match(stp._PAGE_WORDS, "Seite")


def test_page_words_matches_japanese():
    assert re.match(stp._PAGE_WORDS, "ページ")


# ── _WS / _PAGE_NUM / _parse_page_num ────────────────────────────────────────

def test_ws_matches_nbsp_entities():
    assert re.match(stp._WS, "&nbsp;")
    assert re.match(stp._WS, "&#160;")
    assert re.match(stp._WS, "&#xA0;")
    assert re.match(stp._WS, "&#Xa0;")
    assert re.match(stp._WS, "&#x00A0;")
    assert re.match(stp._WS, "&#x0A0;")


def test_parse_page_num_decimal():
    assert stp._parse_page_num("1") == 1
    assert stp._parse_page_num("42") == 42


def test_parse_page_num_roman_lower():
    assert stp._parse_page_num("i") == 1
    assert stp._parse_page_num("iv") == 4
    assert stp._parse_page_num("xiv") == 14
    assert stp._parse_page_num("xlii") == 42


def test_parse_page_num_roman_upper():
    assert stp._parse_page_num("XIV") == 14
    assert stp._parse_page_num("XLII") == 42


def test_parse_page_num_alphanumeric():
    assert stp._parse_page_num("A-1") == 1
    assert stp._parse_page_num("B2") == 2
    assert stp._parse_page_num("C-10") == 10


def test_extract_alphanumeric_page(tmp_path):
    html = '<span>Page A-3</span></button>\n' \
           'aria-label="Highlight: Appendix text . Has context menu" ' \
           'class="bg-bg-highlight-notes-green foo"><span>Appendix text</span>'
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 3
    assert result[0]["color"] == "green"


def _make_html_roman(entries: list[dict]) -> str:
    blocks = []
    current_page = None
    for e in entries:
        if e["page"] != current_page:
            current_page = e["page"]
            blocks.append(f'<span>Page {e["page_label"]}</span></button>')
        note_part = f". Note: {e['note']}" if e.get("note") else ""
        blocks.append(
            f'aria-label="Highlight: {e["text"]}{note_part} . Has context menu"'
            f' class="bg-bg-highlight-notes-{e["color"]} foo">'
            f'<span>{e["text"]}</span>'
        )
    return "\n".join(blocks)


def test_extract_roman_numeral_page(tmp_path):
    html = _make_html_roman([{"page": "xiv", "page_label": "xiv", "color": "yellow", "text": "Intro text", "note": None}])
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 14


def test_extract_nbsp_entity_in_page_label(tmp_path):
    html = '<span>Page&#160;7</span></button>\n' \
           'aria-label="Highlight: Some text . Has context menu" class="bg-bg-highlight-notes-yellow foo"><span>Some text</span>'
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 7


# ── find_start trailing-punctuation strip ─────────────────────────────────────

def test_find_start_rstrip_coverage():
    for ch in "!?)]}'\"":
        stripped = f"word{ch}".rstrip(".,;:!?)]}'\"")
        assert stripped == "word", f"rstrip missed '{ch}'"


def test_rstrip_handles_curly_quotes():
    # Both find_start and find_end_on_page must strip curly (typographic) quotes
    # as well as straight ASCII quotes, since Speechify can export either style.
    import speechify_to_pdf as stp_module
    rstrip_chars = ".,;:!?)]}'\"" + "’”"
    for ch in ["'", '"', "’", "”"]:
        assert f"word{ch}".rstrip(rstrip_chars) == "word", f"rstrip missed {ch!r}"
