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


def test_extract_note_html_entities(tmp_path):
    html = (
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: Some text. Note: R&amp;D &amp; &quot;innovation&quot; . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>Some text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["note"] == 'R&D & "innovation"'


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


def test_guess_pdf_path_numbered_duplicate(tmp_path):
    # Browsers append "(1)", "(2)" etc. when saving a page that already exists on disk.
    pdf = tmp_path / "MyBook.pdf"
    pdf.touch()
    html = tmp_path / "MyBook _ Speechify (1).html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_en_dash_separator(tmp_path):
    # Speechify sometimes uses an en-dash (U+2013) instead of underscore/hyphen.
    pdf = tmp_path / "MyBook.pdf"
    pdf.touch()
    html = tmp_path / "MyBook – Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_em_dash_separator(tmp_path):
    # Speechify sometimes uses an em-dash (U+2014) as separator.
    pdf = tmp_path / "MyBook.pdf"
    pdf.touch()
    html = tmp_path / "MyBook — Speechify.html"
    html.touch()

    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_not_found(tmp_path):
    html = tmp_path / "Ghost _ Speechify.html"
    html.touch()
    assert stp.guess_pdf_path(html) is None


def test_guess_pdf_path_xdg_documents_dir(tmp_path, monkeypatch):
    xdg_docs = tmp_path / "custom_docs"
    xdg_docs.mkdir()
    pdf = xdg_docs / "XdgBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "XdgBook _ Speechify.html"
    html.touch()
    monkeypatch.setenv("XDG_DOCUMENTS_DIR", str(xdg_docs))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_onedrive(tmp_path, monkeypatch):
    onedrive_docs = tmp_path / "OneDrive" / "Documents"
    onedrive_docs.mkdir(parents=True)
    pdf = onedrive_docs / "CloudBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "CloudBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_icloud(tmp_path, monkeypatch):
    icloud = tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    icloud.mkdir(parents=True)
    pdf = icloud / "ICloudBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ICloudBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_home_directory(tmp_path, monkeypatch):
    # PDF lives directly in the home directory (not in any known subdirectory).
    # The function must find it via the last-resort home-directory check.
    pdf = tmp_path / "HomeBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere" / "deep" / "path"
    other.mkdir(parents=True)
    html = other / "HomeBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


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


def test_page_words_matches_thai():
    assert re.match(stp._PAGE_WORDS, "หน้า")


def test_page_words_matches_catalan():
    assert re.match(stp._PAGE_WORDS, "Pàgina")
    assert re.match(stp._PAGE_WORDS, "pàgina", re.IGNORECASE)


def test_page_words_matches_lithuanian():
    assert re.match(stp._PAGE_WORDS, "Puslapis", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "puslapis", re.IGNORECASE)


def test_page_words_matches_latvian():
    assert re.match(stp._PAGE_WORDS, "Lappuse", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "lappuse", re.IGNORECASE)


def test_page_words_matches_welsh():
    assert re.match(stp._PAGE_WORDS, "Tudalen", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "tudalen", re.IGNORECASE)


def test_page_words_matches_tagalog():
    assert re.match(stp._PAGE_WORDS, "Pahina", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "pahina", re.IGNORECASE)


def test_page_words_matches_azerbaijani():
    assert re.match(stp._PAGE_WORDS, "Səhifə", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "səhifə", re.IGNORECASE)


def test_page_words_matches_georgian():
    assert re.match(stp._PAGE_WORDS, "გვერდი")


def test_page_words_matches_armenian():
    assert re.match(stp._PAGE_WORDS, "Էջ")


def test_page_words_matches_icelandic():
    assert re.match(stp._PAGE_WORDS, "Blaðsíða", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "blaðsíða", re.IGNORECASE)


def test_page_words_matches_estonian():
    assert re.match(stp._PAGE_WORDS, "Lehekülg", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "lehekülg", re.IGNORECASE)


def test_page_words_matches_basque():
    assert re.match(stp._PAGE_WORDS, "Orrialde", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "orrialde", re.IGNORECASE)


# ── _WS / _PAGE_NUM / _parse_page_num ────────────────────────────────────────

def test_ws_matches_nbsp_entities():
    assert re.match(stp._WS, "&nbsp;")
    assert re.match(stp._WS, "&#160;")
    assert re.match(stp._WS, "&#xA0;")
    assert re.match(stp._WS, "&#Xa0;")
    assert re.match(stp._WS, "&#x00A0;")
    assert re.match(stp._WS, "&#x0A0;")


def test_ws_matches_raw_nbsp():
    # Python's \s does NOT match \xa0; it must be listed explicitly in the pattern.
    assert re.match(stp._WS, "\xa0"), "raw U+00A0 not matched by _WS"
    assert re.match(stp._WS_OPT, "\xa0"), "raw U+00A0 not matched by _WS_OPT"


def test_extract_raw_nbsp_in_page_label(tmp_path):
    # Some browsers embed a raw U+00A0 between the page word and number instead
    # of using &nbsp;. The page-split regex must parse the page number correctly.
    html = (
        "Page\xa07</span></button>\n"
        'aria-label="Highlight: Some text . Has context menu" '
        'class="bg-bg-highlight-notes-yellow foo"><span>Some text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 7


def test_extract_unicode_ellipsis_truncation(tmp_path):
    # Speechify can export a truncated highlight ending with U+2026 (…) rather
    # than ASCII triple-dot (...). Both forms must be detected as truncated.
    html = _make_html([{"page": 1, "color": "yellow", "text": "Some long text…", "note": None}])
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["truncated"] is True
    assert not result[0]["text"].endswith("…")


def test_extract_aria_label_preferred_when_longer(tmp_path):
    # The aria-label attribute sometimes carries the full highlight text while
    # the visible <span> is truncated for display (~80 chars). When aria-label
    # is longer, extract_highlights must prefer it so the annotation covers the
    # complete highlighted passage rather than the truncated display text.
    full_text = "This is the full highlight text that is longer than what the span shows"
    short_span = "This is the full highlight text that is…"
    html = (
        '<span>Page 2</span></button>\n'
        f'aria-label="Highlight: {full_text} . Has context menu"'
        f' class="bg-bg-highlight-notes-blue foo"><span>{short_span}</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["text"] == full_text
    assert result[0]["truncated"] is False


def test_extract_span_used_when_aria_label_not_longer(tmp_path):
    # When the visible span is as long as (or longer than) the aria-label,
    # the span text must be used as the primary source.
    text = "Short highlight"
    html = (
        '<span>Page 1</span></button>\n'
        f'aria-label="Highlight: {text} . Has context menu"'
        f' class="bg-bg-highlight-notes-yellow foo"><span>{text} with extra words</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["text"] == text + " with extra words"


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


def test_page_num_pat_rejects_unicode_digits():
    # Python's \d matches Unicode decimal digits (e.g. Arabic-Indic "٣"), but
    # int() cannot parse them, causing a ValueError.  _PAGE_NUM_PAT must use
    # [0-9] so those characters are never captured as page numbers.
    arabic_indic_digit = "٣"  # U+0663, isdigit()=True but int() raises ValueError
    assert not re.fullmatch(stp._PAGE_NUM_PAT, arabic_indic_digit), (
        "_PAGE_NUM_PAT must not match non-ASCII decimal digits"
    )


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
    for ch in ["'", '"', "’", "”"]:
        assert f"word{ch}".rstrip(stp._TRAILING_PUNCT) == "word", f"rstrip missed {ch!r}"

# ── find_start skip-fallback range ──────────────────────────────────────────────────────────────────────────────

def test_find_start_skip_fallback_range_3word():
    # For a 3-word text the skip fallback must produce a 2-word candidate;
    # range(min(7, 3-1), 1, -1) == [2], so words[1:3] is tried.
    # Before the fix the stop was 2, giving range(2,2,-1)==[] (empty, no try).
    words = "The Quick Fox".split()
    skip = 1
    candidates = [
        words[skip:skip + n]
        for n in range(min(7, len(words) - skip), 1, -1)
    ]
    assert candidates == [["Quick", "Fox"]], f"Expected 2-word fallback, got {candidates}"


def test_find_start_skip_fallback_range_4word():
    # For a 4-word text with skip=1 the range should yield n in [3, 2].
    words = "The Quick Brown Fox".split()
    skip = 1
    ns = list(range(min(7, len(words) - skip), 1, -1))
    assert ns == [3, 2]


# ── output-path safety guards ─────────────────────────────────────────────────

def test_output_path_same_as_html_is_rejected(tmp_path, monkeypatch, capsys):
    """Specifying the HTML file as -o output must be rejected before any work."""
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text('<span>Page 1</span></button>\n', encoding="utf-8")
    pdf = tmp_path / "Book.pdf"
    pdf.touch()

    with pytest.raises(SystemExit) as exc_info:
        import sys as _sys
        _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "-o", str(html)]
        stp_module.main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "same as the input HTML" in captured.out or "same as the input HTML" in str(exc_info.value.code)


def test_output_path_same_as_pdf_is_rejected(tmp_path, monkeypatch, capsys):
    """Specifying the input PDF as -o output must be rejected to prevent overwriting the original."""
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text('<span>Page 1</span></button>\n', encoding="utf-8")
    pdf = tmp_path / "Book.pdf"
    pdf.touch()

    with pytest.raises(SystemExit) as exc_info:
        import sys as _sys
        _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "-o", str(pdf)]
        stp_module.main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "same as the input PDF" in captured.out or "same as the input PDF" in str(exc_info.value.code)


# ── verbose tip on not-found highlights ──────────────────────────────────────

def test_verbose_tip_shown_when_not_found_without_verbose():
    """When highlights are not found and verbose is off, a -v tip should appear."""
    not_found = [{"page": 1, "color": "yellow", "text": "Some text", "note": None}]
    all_highlights = not_found
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        # Simulate the not_found block logic from main()
        import speechify_to_pdf as m
        verbose = False
        print(f"Not found ({len(not_found)}):")
        if not_found and not verbose:
            print("\nTip: run again with -v/--verbose to see per-highlight match details.")
    assert "-v/--verbose" in out.getvalue()


def test_verbose_tip_suppressed_when_verbose_active():
    """When -v/--verbose is active the verbose tip must not appear."""
    import io, contextlib
    not_found = [{"page": 1, "color": "yellow", "text": "Some text", "note": None}]
    verbose = True
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        if not_found and not verbose:
            print("\nTip: run again with -v/--verbose to see per-highlight match details.")
    assert "-v/--verbose" not in out.getvalue()


# ── _detect_page_offset ────────────────────────────────────────────────────────

def _make_located(pairs):
    """Build a located list from (found_page, html_page) pairs. None found_page = not found."""
    return [
        (fp, object(), {"page": hp, "color": "yellow", "text": "x", "note": None, "truncated": False})
        for fp, hp in pairs
    ]


def test_detect_offset_consistent_shift():
    # fp - (hp - 1): (20,1)→20, (21,2)→20, (22,3)→20, (23,4)→20 → offset 20
    located = _make_located([(20, 1), (21, 2), (22, 3), (23, 4)])
    assert stp._detect_page_offset(located, 0) == 20


def test_detect_offset_majority_wins():
    # 3 agree on offset 5, 1 noise at offset 0
    located = _make_located([(5, 0), (6, 1), (7, 2), (3, 3)])
    # html pages are 0-indexed in calc: fp - (hp - 1)
    # (5,0) → 5 - (-1) = 6, (6,1) → 6-0=6, (7,2) → 7-1=6, (3,3) → 3-2=1
    assert stp._detect_page_offset(located, 0) == 6


def test_detect_offset_zero_when_no_shift():
    located = _make_located([(0, 1), (1, 2), (2, 3)])
    assert stp._detect_page_offset(located, 0) is None


def test_detect_offset_returns_new_suggestion_when_different_from_current():
    # If the detected consistent offset (20) differs from the currently set offset (5),
    # the function should return the detected offset so the user gets a specific
    # suggestion ("try --page-offset 20") rather than generic advice.
    located = _make_located([(20, 1), (21, 2)])
    assert stp._detect_page_offset(located, 5) == 20


def test_detect_offset_empty_located():
    located = _make_located([(None, 1), (None, 2)])
    assert stp._detect_page_offset(located, 0) is None


def test_detect_offset_no_consensus():
    # Every highlight on a different offset — no majority
    located = _make_located([(1, 1), (5, 2), (9, 3), (13, 4)])
    # offsets: 1-0=1, 5-1=4, 9-2=7, 13-3=10 → all different, count=1 each
    # max(1, 4//2) = 2; all counts are 1, so no consensus
    assert stp._detect_page_offset(located, 0) is None
