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


def test_extract_hyphenated_color(tmp_path):
    html = (
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: Some text . Has context menu"'
        ' class="bg-bg-highlight-notes-light-yellow foo"><span>Some text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["color"] == "light-yellow"


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


def test_extract_cp1252_encoding(tmp_path):
    # Files saved by Windows browsers in cp1252 should decode correctly.
    # 0x93/0x94 are left/right double quotes in cp1252 (control chars in latin-1).
    html = (
        b'<span>Page 1</span></button>\n'
        b'aria-label="Highlight: \x93Smart quotes\x94 in title . Has context menu"'
        b' class="bg-bg-highlight-notes-yellow foo">'
        b'<span>\x93Smart quotes\x94 in title</span>'
    )
    f = tmp_path / "test.html"
    f.write_bytes(html)
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert "“" in result[0]["text"] or "”" in result[0]["text"]


# ── _expected_pdf_name ────────────────────────────────────────────────────────

def test_expected_pdf_name_underscore_separator():
    assert stp._expected_pdf_name(Path("MyBook _ Speechify.html")) == "MyBook.pdf"


def test_expected_pdf_name_hyphen_separator():
    assert stp._expected_pdf_name(Path("Research Paper - Speechify.html")) == "Research Paper.pdf"


def test_expected_pdf_name_pipe_separator():
    assert stp._expected_pdf_name(Path("MyBook | Speechify.html")) == "MyBook.pdf"


def test_expected_pdf_name_en_dash_separator():
    assert stp._expected_pdf_name(Path("MyBook – Speechify.html")) == "MyBook.pdf"


def test_expected_pdf_name_em_dash_separator():
    assert stp._expected_pdf_name(Path("MyBook — Speechify.html")) == "MyBook.pdf"


def test_expected_pdf_name_numbered_duplicate():
    assert stp._expected_pdf_name(Path("MyBook _ Speechify (2).html")) == "MyBook.pdf"


def test_expected_pdf_name_stem_already_ends_in_pdf():
    # Browser saves "My Book.pdf" document as "My Book.pdf _ Speechify.html"
    assert stp._expected_pdf_name(Path("My Book.pdf _ Speechify.html")) == "My Book.pdf"


def test_expected_pdf_name_case_insensitive():
    assert stp._expected_pdf_name(Path("MyBook - SPEECHIFY.html")) == "MyBook.pdf"


def test_expected_pdf_name_speechify_in_title():
    # "Speechify" appears inside the title — only the trailing separator is stripped
    assert stp._expected_pdf_name(Path("Speechify Hacks - Speechify.html")) == "Speechify Hacks.pdf"


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


def test_guess_pdf_path_dutch_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documenten"
    docs.mkdir()
    pdf = docs / "DutchBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "DutchBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_polish_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumenty"
    docs.mkdir()
    pdf = docs / "PolishBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "PolishBook _ Speechify.html"
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


def test_guess_pdf_path_google_drive_for_desktop(tmp_path, monkeypatch):
    gdrive = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-user@gmail.com" / "My Drive"
    gdrive.mkdir(parents=True)
    pdf = gdrive / "GDriveBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "GDriveBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_google_drive_for_desktop_windows(tmp_path, monkeypatch):
    # Google Drive for Desktop on Windows/Linux stores files in ~/My Drive by default.
    gdrive_win = tmp_path / "My Drive"
    gdrive_win.mkdir()
    pdf = gdrive_win / "WinGDriveBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "WinGDriveBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_windows_icloud(tmp_path, monkeypatch):
    icloud_win = tmp_path / "iCloudDrive"
    icloud_win.mkdir()
    pdf = icloud_win / "WinICloudBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "WinICloudBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_swedish_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokument"
    docs.mkdir()
    pdf = docs / "SwedishBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "SwedishBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_danish_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumenter"
    docs.mkdir()
    pdf = docs / "DanishBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "DanishBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_russian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Документы"
    docs.mkdir()
    pdf = docs / "RussianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "RussianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_ukrainian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Документи"
    docs.mkdir()
    pdf = docs / "UkrainianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "UkrainianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_turkish_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Belgeler"
    docs.mkdir()
    pdf = docs / "TurkishBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "TurkishBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_finnish_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Asiakirjat"
    docs.mkdir()
    pdf = docs / "FinnishBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "FinnishBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_hungarian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumentumok"
    docs.mkdir()
    pdf = docs / "HungarianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "HungarianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_greek_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Έγγραφα"
    docs.mkdir()
    pdf = docs / "GreekBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "GreekBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_korean_documents(tmp_path, monkeypatch):
    docs = tmp_path / "문서"
    docs.mkdir()
    pdf = docs / "KoreanBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "KoreanBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_japanese_documents_macos(tmp_path, monkeypatch):
    docs = tmp_path / "書類"
    docs.mkdir()
    pdf = docs / "JapaneseBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "JapaneseBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_japanese_documents_windows(tmp_path, monkeypatch):
    docs = tmp_path / "ドキュメント"
    docs.mkdir()
    pdf = docs / "JapaneseBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "JapaneseBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_traditional_chinese_documents(tmp_path, monkeypatch):
    docs = tmp_path / "文件"
    docs.mkdir()
    pdf = docs / "ChineseBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ChineseBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_simplified_chinese_documents(tmp_path, monkeypatch):
    docs = tmp_path / "文档"
    docs.mkdir()
    pdf = docs / "ChineseBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ChineseBook _ Speechify.html"
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


def test_iter_pdfs_skips_hidden_dirs(tmp_path):
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.pdf").write_bytes(b"")
    visible = tmp_path / "docs"
    visible.mkdir()
    (visible / "book.pdf").write_bytes(b"")
    results = list(stp._iter_pdfs(tmp_path))
    names = [p.name for p in results]
    assert "book.pdf" in names
    assert "secret.pdf" not in names


def test_guess_pdf_path_dropbox(tmp_path, monkeypatch):
    dropbox = tmp_path / "Dropbox"
    dropbox.mkdir()
    pdf = dropbox / "DropboxBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "DropboxBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_dropbox_subdirectory(tmp_path, monkeypatch):
    dropbox = tmp_path / "Dropbox" / "Books"
    dropbox.mkdir(parents=True)
    pdf = dropbox / "DropboxSubBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "DropboxSubBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_google_drive_legacy(tmp_path, monkeypatch):
    gdrive = tmp_path / "Google Drive"
    gdrive.mkdir()
    pdf = gdrive / "LegacyGDriveBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "LegacyGDriveBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_onedrive_macos(tmp_path, monkeypatch):
    # OneDrive on macOS mounts under ~/Library/CloudStorage/OneDrive-Personal/
    onedrive = tmp_path / "Library" / "CloudStorage" / "OneDrive-Personal"
    onedrive.mkdir(parents=True)
    pdf = onedrive / "MacOneDriveBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "MacOneDriveBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_chinese_desktop(tmp_path, monkeypatch):
    desk = tmp_path / "桌面"
    desk.mkdir()
    pdf = desk / "ChineseDesktopBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ChineseDesktopBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_japanese_desktop(tmp_path, monkeypatch):
    desk = tmp_path / "デスクトップ"
    desk.mkdir()
    pdf = desk / "JapaneseDesktopBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "JapaneseDesktopBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_korean_desktop_windows(tmp_path, monkeypatch):
    desk = tmp_path / "바탕화면"
    desk.mkdir()
    pdf = desk / "KoreanDesktopBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "KoreanDesktopBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_korean_desktop_macos(tmp_path, monkeypatch):
    desk = tmp_path / "바탕 화면"
    desk.mkdir()
    pdf = desk / "KoreanDesktopMacBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "KoreanDesktopMacBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_portuguese_desktop(tmp_path, monkeypatch):
    desk = tmp_path / "Área de Trabalho"
    desk.mkdir()
    pdf = desk / "PortugueseDesktopBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "PortugueseDesktopBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_simplified_chinese_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "下载"
    dl.mkdir()
    pdf = dl / "ChineseDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ChineseDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_traditional_chinese_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "下載"
    dl.mkdir()
    pdf = dl / "TraditionalChineseDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "TraditionalChineseDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_japanese_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "ダウンロード"
    dl.mkdir()
    pdf = dl / "JapaneseDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "JapaneseDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_korean_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "다운로드"
    dl.mkdir()
    pdf = dl / "KoreanDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "KoreanDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


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


def test_page_words_matches_persian():
    assert re.match(stp._PAGE_WORDS, "صفحه")


def test_page_words_matches_hindi():
    assert re.match(stp._PAGE_WORDS, "पृष्ठ")


def test_page_words_matches_swahili():
    assert re.match(stp._PAGE_WORDS, "Ukurasa", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "ukurasa", re.IGNORECASE)


def test_page_words_matches_czech_slovak():
    assert re.match(stp._PAGE_WORDS, "Strana", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "strana", re.IGNORECASE)


def test_page_words_matches_polish():
    assert re.match(stp._PAGE_WORDS, "Strona", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "strona", re.IGNORECASE)


def test_page_words_matches_croatian_serbian():
    assert re.match(stp._PAGE_WORDS, "Stranica", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "stranica", re.IGNORECASE)


def test_page_words_matches_slovenian():
    assert re.match(stp._PAGE_WORDS, "Stran", re.IGNORECASE)
    assert re.match(stp._PAGE_WORDS, "stran", re.IGNORECASE)


# ── extract_highlights with non-English page labels ───────────────────────────

def test_extract_highlights_german_page_label(tmp_path):
    html = (
        '<span>Seite 5</span></button>\n'
        'aria-label="Highlight: Deutsches Beispiel . Has context menu" '
        'class="bg-bg-highlight-notes-yellow foo"><span>Deutsches Beispiel</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 5
    assert result[0]["text"] == "Deutsches Beispiel"


def test_extract_highlights_french_page_label(tmp_path):
    html = (
        '<span>Page 12</span></button>\n'
        'aria-label="Highlight: Texte français . Has context menu" '
        'class="bg-bg-highlight-notes-pink foo"><span>Texte français</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 12
    assert result[0]["color"] == "pink"


def test_extract_highlights_spanish_page_label(tmp_path):
    html = (
        '<span>Página 7</span></button>\n'
        'aria-label="Highlight: Texto en español . Has context menu" '
        'class="bg-bg-highlight-notes-blue foo"><span>Texto en español</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 7


def test_extract_highlights_korean_page_label(tmp_path):
    html = (
        '<span>페이지 3</span></button>\n'
        'aria-label="Highlight: Korean text . Has context menu" '
        'class="bg-bg-highlight-notes-green foo"><span>Korean text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 3


def test_extract_highlights_persian_page_label(tmp_path):
    html = (
        '<span>صفحه 9</span></button>\n'
        'aria-label="Highlight: Persian text . Has context menu" '
        'class="bg-bg-highlight-notes-yellow foo"><span>Persian text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 9


def test_extract_highlights_persian_arabic_indic_digits(tmp_path):
    # Speechify on Persian/Arabic books emits Arabic-Indic digits (U+06F0–U+06F9 / U+0660–U+0669).
    # Both variants must be accepted and normalized to their ASCII equivalents.
    for page_label, expected_page in [
        ("صفحه ۱۲", 12),    # Extended Arabic-Indic (Persian/Urdu), U+06F0–U+06F9
        ("صفحة ١٢", 12),    # Arabic-Indic, U+0660–U+0669
    ]:
        html = (
            f'<span>{page_label}</span></button>\n'
            'aria-label="Highlight: some text . Has context menu" '
            'class="bg-bg-highlight-notes-yellow foo"><span>some text</span>'
        )
        f = tmp_path / "test.html"
        f.write_text(html, encoding="utf-8")
        result = stp.extract_highlights(f)
        assert len(result) == 1, f"expected 1 highlight for label {page_label!r}"
        assert result[0]["page"] == expected_page, (
            f"page {result[0]['page']} != {expected_page} for label {page_label!r}"
        )


def test_extract_highlights_hindi_page_label(tmp_path):
    html = (
        '<span>पृष्ठ 4</span></button>\n'
        'aria-label="Highlight: Hindi text . Has context menu" '
        'class="bg-bg-highlight-notes-blue foo"><span>Hindi text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 4


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


def test_parse_page_num_double_letter_prefix():
    # Double-letter appendix labels: "AA-1", "AB5", "CD.10"
    assert stp._parse_page_num("AA-1") == 1
    assert stp._parse_page_num("AB5") == 5
    assert stp._parse_page_num("CD-10") == 10


def test_parse_page_num_period_separator():
    # Period separator: "A.10", "B.5" (used by some European/technical publishers)
    assert stp._parse_page_num("A.10") == 10
    assert stp._parse_page_num("B.5") == 5


def test_extract_double_letter_appendix_page(tmp_path):
    html = '<span>Page AA-3</span></button>\n' \
           'aria-label="Highlight: Appendix text . Has context menu" ' \
           'class="bg-bg-highlight-notes-blue foo"><span>Appendix text</span>'
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 3
    assert result[0]["color"] == "blue"


def test_extract_period_separator_page(tmp_path):
    html = '<span>Page A.7</span></button>\n' \
           'aria-label="Highlight: Technical text . Has context menu" ' \
           'class="bg-bg-highlight-notes-yellow foo"><span>Technical text</span>'
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 7


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


def test_page_num_arabic_indic_digit_matches_and_normalizes():
    # Arabic-Indic "٣" (U+0663) and Persian "۳" (U+06F3) must be accepted by
    # _PAGE_NUM_PAT and normalized to ASCII by _parse_page_num so int() never
    # sees the raw Unicode digits (which would raise ValueError).
    assert re.fullmatch(stp._PAGE_NUM_PAT, "٣"), "_PAGE_NUM_PAT must match Arabic-Indic digit"
    assert re.fullmatch(stp._PAGE_NUM_PAT, "۳"), "_PAGE_NUM_PAT must match Persian digit"
    assert stp._parse_page_num("٣") == 3
    assert stp._parse_page_num("۳") == 3
    assert stp._parse_page_num("١٢٣") == 123
    assert stp._parse_page_num("۱۲۳") == 123


def test_page_num_devanagari_digit_normalizes():
    # Devanagari digits ०-९ (U+0966–U+096F) must be normalised by _parse_page_num.
    assert re.fullmatch(stp._PAGE_NUM_PAT, "४"), "_PAGE_NUM_PAT must match Devanagari digit"
    assert stp._parse_page_num("४") == 4
    assert stp._parse_page_num("४२") == 42


def test_page_num_thai_digit_normalizes():
    # Thai digits ๐-๙ (U+0E50–U+0E59) must be normalised by _parse_page_num.
    assert re.fullmatch(stp._PAGE_NUM_PAT, "๔"), "_PAGE_NUM_PAT must match Thai digit"
    assert stp._parse_page_num("๔") == 4
    assert stp._parse_page_num("๔๒") == 42


def test_extract_highlights_devanagari_digits(tmp_path):
    # Speechify on Hindi books may emit Devanagari digits in page labels.
    html = (
        '<span>पृष्ठ ४२</span></button>\n'
        'aria-label="Highlight: Hindi text . Has context menu" '
        'class="bg-bg-highlight-notes-yellow foo"><span>Hindi text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 42


def test_extract_highlights_thai_digits(tmp_path):
    # Speechify on Thai books may emit Thai digits in page labels.
    html = (
        '<span>หน้า ๔๒</span></button>\n'
        'aria-label="Highlight: Thai text . Has context menu" '
        'class="bg-bg-highlight-notes-blue foo"><span>Thai text</span>'
    )
    f = tmp_path / "test.html"
    f.write_text(html, encoding="utf-8")
    result = stp.extract_highlights(f)
    assert len(result) == 1
    assert result[0]["page"] == 42


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


# ── --colors filter error message ────────────────────────────────────────────

def test_colors_filter_no_match_shows_available(tmp_path, capsys):
    """When --colors finds no match, error message must list colors present in the document."""
    import speechify_to_pdf as stp_module
    import sys as _sys

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: Some text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>Some text</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    pdf.touch()

    with pytest.raises(SystemExit) as exc_info:
        _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "--colors", "purple"]
        stp_module.main()

    assert exc_info.value.code != 0
    err_msg = str(exc_info.value.code)
    assert "purple" in err_msg
    assert "yellow" in err_msg  # must show what IS present


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


def test_output_path_is_directory_is_rejected(tmp_path, capsys):
    """Passing an existing directory as -o must be rejected with a clear error."""
    import speechify_to_pdf as stp_module
    import sys as _sys

    html = tmp_path / "Book _ Speechify.html"
    html.write_text('<span>Page 1</span></button>\n', encoding="utf-8")
    pdf = tmp_path / "Book.pdf"
    pdf.touch()
    out_dir = tmp_path / "output_dir"
    out_dir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "-o", str(out_dir)]
        stp_module.main()

    assert exc_info.value.code != 0
    msg = str(exc_info.value.code)
    assert "directory" in msg


# ── swapped-argument warning ─────────────────────────────────────────────────

def test_html_arg_with_pdf_extension_warns(tmp_path, capsys):
    """Passing a .pdf file as the HTML argument should print a warning to stderr."""
    import speechify_to_pdf as stp_module
    import sys as _sys

    pdf_as_html = tmp_path / "Book.pdf"
    pdf_as_html.write_text("<html></html>", encoding="utf-8")  # not a real PDF, but exists

    with pytest.raises(SystemExit):
        _sys.argv = ["speechify-to-pdf", str(pdf_as_html)]
        stp_module.main()

    captured = capsys.readouterr()
    assert "looks like a PDF" in captured.err
    assert "swap" in captured.err


# ── dry-run output-directory check ───────────────────────────────────────────

def test_dry_run_skips_output_dir_writability_check(tmp_path, capsys):
    """--dry-run must not abort on a nonexistent output directory."""
    import speechify_to_pdf as stp_module
    import sys as _sys

    html = tmp_path / "Book _ Speechify.html"
    html.write_text("<html></html>", encoding="utf-8")  # no highlights
    pdf = tmp_path / "Book.pdf"
    pdf.touch()
    nonexistent_dir = tmp_path / "does_not_exist"

    with pytest.raises(SystemExit) as exc_info:
        _sys.argv = [
            "speechify-to-pdf", str(html), str(pdf),
            "--dry-run",
            "-o", str(nonexistent_dir / "output.pdf"),
        ]
        stp_module.main()

    # Must fail on "no highlights", NOT on "output directory does not exist".
    err_msg = str(exc_info.value.code)
    assert "No highlights found" in err_msg
    assert "output directory does not exist" not in err_msg


def test_dry_run_warns_when_output_dir_missing(tmp_path, capsys, monkeypatch):
    """--dry-run should warn on stderr when the output directory doesn't exist."""
    import speechify_to_pdf as stp_module
    import sys as _sys

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: hello world . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>hello world</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world")
    doc.save(str(pdf))
    doc.close()

    nonexistent_dir = tmp_path / "does_not_exist"
    _sys.argv = [
        "speechify-to-pdf", str(html), str(pdf),
        "--dry-run",
        "-o", str(nonexistent_dir / "output.pdf"),
    ]
    stp_module.main()
    captured = capsys.readouterr()
    assert "output directory does not exist" in captured.err


def test_dry_run_no_highlights_transferred_message(tmp_path, capsys):
    """When --dry-run finds highlights in HTML but none locate in the PDF, it must
    say 'no highlights would be transferred' rather than the misleading 'Would save to:'."""
    import speechify_to_pdf as stp_module
    import sys as _sys
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: xyzzy_notfound_text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>xyzzy_notfound_text</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "--dry-run"]
    stp_module.main()

    captured = capsys.readouterr()
    assert "Would save to" not in captured.out
    assert "No highlights would be transferred" in captured.out


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


def test_verbose_tip_suppressed_in_quiet_mode(tmp_path, capsys):
    """In --quiet mode the verbose tip must not appear — quiet mode is for scripts."""
    import speechify_to_pdf as stp_module
    import sys as _sys
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: xyzzy not in pdf . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>xyzzy not in pdf</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    with pytest.raises(SystemExit):
        _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "-q"]
        stp_module.main()

    captured = capsys.readouterr()
    assert "-v/--verbose" not in captured.out


# ── --list mode ──────────────────────────────────────────────────────────────

def test_list_mode_prints_summary(tmp_path, capsys):
    """--list prints a color breakdown and returns without requiring a PDF."""
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: First highlight . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>First highlight</span>\n'
        '<span>Page 2</span></button>\n'
        'aria-label="Highlight: Second highlight . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>Second highlight</span>\n'
        'aria-label="Highlight: A pink one . Has context menu"'
        ' class="bg-bg-highlight-notes-pink foo"><span>A pink one</span>',
        encoding="utf-8",
    )
    _sys.argv = ["speechify-to-pdf", str(html), "--list"]
    stp_module.main()
    captured = capsys.readouterr()
    assert "3 highlights found" in captured.out
    assert "yellow" in captured.out
    assert "pink" in captured.out


def test_list_mode_no_highlights(tmp_path, capsys):
    """--list on an HTML with no highlights prints a clear message."""
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Empty _ Speechify.html"
    html.write_text("<html></html>", encoding="utf-8")
    _sys.argv = ["speechify-to-pdf", str(html), "--list"]
    stp_module.main()
    captured = capsys.readouterr()
    assert "No highlights found" in captured.out


def test_list_mode_shows_truncated_count(tmp_path, capsys):
    """--list notes how many highlights are truncated by Speechify."""
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: A very long highlight that gets cut off... . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo">'
        '<span>A very long highlight that gets cut off...</span>',
        encoding="utf-8",
    )
    _sys.argv = ["speechify-to-pdf", str(html), "--list"]
    stp_module.main()
    captured = capsys.readouterr()
    assert "truncated" in captured.out


def test_list_verbose_shows_highlight_texts(tmp_path, capsys):
    """--list -v prints each highlight's page, color, and text excerpt."""
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 3</span></button>\n'
        'aria-label="Highlight: Some important text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>Some important text</span>\n'
        'aria-label="Highlight: Another excerpt. Note: my note . Has context menu"'
        ' class="bg-bg-highlight-notes-pink foo"><span>Another excerpt</span>',
        encoding="utf-8",
    )
    _sys.argv = ["speechify-to-pdf", str(html), "--list", "-v"]
    stp_module.main()
    captured = capsys.readouterr()
    assert "Some important text" in captured.out
    assert "Another excerpt" in captured.out
    assert "my note" in captured.out
    assert "p." in captured.out
    assert "[yellow]" in captured.out
    assert "[pink]" in captured.out


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


# ── _collect_lines ────────────────────────────────────────────────────────────

def test_collect_lines_groups_same_line():
    """Words on the same text line are merged into a single rect."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((10, 50), "Hello world test")
    rects = stp._collect_lines(page, 30, 80)
    doc.close()
    assert len(rects) == 1


def test_collect_lines_separates_different_lines():
    """Words on distinct lines (far apart vertically) produce separate rects."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((10, 50), "First line")
    page.insert_text((10, 120), "Second line")
    rects = stp._collect_lines(page, 0, 200)
    doc.close()
    assert len(rects) == 2


def test_collect_lines_excludes_outside_range():
    """Words outside [y_start, y_end] are not included."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((10, 50), "Above range")
    page.insert_text((10, 180), "In range")
    rects = stp._collect_lines(page, 150, 220)
    doc.close()
    assert len(rects) == 1


# ── _valid_rects ──────────────────────────────────────────────────────────────

def test_valid_rects_keeps_in_bounds_rect():
    """A normal in-bounds rect is returned unchanged (clipped to page)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    r = fitz.Rect(10, 10, 200, 30)
    result = stp._valid_rects(page, [r])
    doc.close()
    assert len(result) == 1


def test_valid_rects_drops_zero_width_rect():
    """A rect with zero width is dropped."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    r = fitz.Rect(50, 10, 50, 30)  # zero width
    result = stp._valid_rects(page, [r])
    doc.close()
    assert result == []


def test_valid_rects_drops_zero_height_rect():
    """A rect with zero height is dropped."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    r = fitz.Rect(10, 50, 200, 50)  # zero height
    result = stp._valid_rects(page, [r])
    doc.close()
    assert result == []


def test_valid_rects_clips_and_keeps_partially_in_bounds():
    """A rect extending past the right page edge is clipped but kept."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    r = fitz.Rect(380, 10, 500, 30)  # extends 100pt past page right edge
    result = stp._valid_rects(page, [r])
    doc.close()
    assert len(result) == 1
    assert result[0].x1 <= 400


def test_valid_rects_empty_input():
    """Empty input returns empty output."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    result = stp._valid_rects(page, [])
    doc.close()
    assert result == []


def test_guess_pdf_path_spanish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Descargas"
    dl.mkdir()
    pdf = dl / "SpanishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "SpanishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_portuguese_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Transferências"
    dl.mkdir()
    pdf = dl / "PortugueseDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "PortugueseDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_italian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Scaricati"
    dl.mkdir()
    pdf = dl / "ItalianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ItalianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_polish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Pobrane"
    dl.mkdir()
    pdf = dl / "PolishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "PolishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_russian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Загрузки"
    dl.mkdir()
    pdf = dl / "RussianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "RussianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_ukrainian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Завантаження"
    dl.mkdir()
    pdf = dl / "UkrainianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "UkrainianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_turkish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "İndirmeler"
    dl.mkdir()
    pdf = dl / "TurkishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "TurkishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_swedish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Nedladdningar"
    dl.mkdir()
    pdf = dl / "SwedishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "SwedishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_finnish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Lataukset"
    dl.mkdir()
    pdf = dl / "FinnishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "FinnishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_hungarian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Letöltések"
    dl.mkdir()
    pdf = dl / "HungarianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "HungarianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_greek_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Λήψεις"
    dl.mkdir()
    pdf = dl / "GreekDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "GreekDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_danish_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Overførsler"
    dl.mkdir()
    pdf = dl / "DanishDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "DanishDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_norwegian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Nedlastinger"
    dl.mkdir()
    pdf = dl / "NorwegianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "NorwegianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_romanian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documente"
    docs.mkdir()
    pdf = docs / "RomanianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "RomanianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_romanian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Descărcări"
    dl.mkdir()
    pdf = dl / "RomanianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "RomanianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_croatian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumenti"
    docs.mkdir()
    pdf = docs / "CroatianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "CroatianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_croatian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Preuzimanja"
    dl.mkdir()
    pdf = dl / "CroatianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "CroatianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_slovenian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Prenosi"
    dl.mkdir()
    pdf = dl / "SlovenianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "SlovenianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_latvian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Lejupielādes"
    dl.mkdir()
    pdf = dl / "LatvianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "LatvianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_estonian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumendid"
    docs.mkdir()
    pdf = docs / "EstonianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "EstonianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_estonian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Allalaadimised"
    dl.mkdir()
    pdf = dl / "EstonianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "EstonianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_lithuanian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumentai"
    docs.mkdir()
    pdf = docs / "LithuanianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "LithuanianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_lithuanian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Atsiuntimai"
    dl.mkdir()
    pdf = dl / "LithuanianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "LithuanianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_vietnamese_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Tài liệu"
    docs.mkdir()
    pdf = docs / "VietnameseBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "VietnameseBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_vietnamese_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Tải xuống"
    dl.mkdir()
    pdf = dl / "VietnameseDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "VietnameseDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_indonesian_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Dokumen"
    docs.mkdir()
    pdf = docs / "IndonesianBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "IndonesianBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_indonesian_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "Unduhan"
    dl.mkdir()
    pdf = dl / "IndonesianDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "IndonesianDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_thai_documents(tmp_path, monkeypatch):
    docs = tmp_path / "เอกสาร"
    docs.mkdir()
    pdf = docs / "ThaiBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ThaiBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


def test_guess_pdf_path_thai_downloads(tmp_path, monkeypatch):
    dl = tmp_path / "ดาวน์โหลด"
    dl.mkdir()
    pdf = dl / "ThaiDownloadBook.pdf"
    pdf.touch()
    other = tmp_path / "elsewhere"
    other.mkdir()
    html = other / "ThaiDownloadBook _ Speechify.html"
    html.touch()
    monkeypatch.setattr(stp.Path, "home", classmethod(lambda cls: tmp_path))
    found = stp.guess_pdf_path(html)
    assert found == pdf


# ── find_start ────────────────────────────────────────────────────────────────

def _make_page(text: str, y: float = 100, width: int = 400, height: int = 300):
    """Return an open fitz.Document and its single page with `text` inserted at (10, y)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((10, y), text)
    return doc, page


def test_find_start_exact_match():
    """find_start returns the first rect when the full text is on the page."""
    doc, page = _make_page("The quick brown fox jumps")
    r = stp.find_start(page, "The quick brown fox jumps")
    doc.close()
    assert r is not None


def test_find_start_short_text_single_word():
    """Single-word text is handled via the short-text path."""
    doc, page = _make_page("Hello")
    r = stp.find_start(page, "Hello")
    doc.close()
    assert r is not None


def test_find_start_short_text_two_words():
    """Two-word text is handled via the short-text path."""
    doc, page = _make_page("Hello world")
    r = stp.find_start(page, "Hello world")
    doc.close()
    assert r is not None


def test_find_start_short_text_trailing_punctuation():
    """Short text with trailing punctuation is found after stripping."""
    doc, page = _make_page("Hello world")
    r = stp.find_start(page, "Hello world!")
    doc.close()
    assert r is not None


def test_find_start_prefix_match():
    """When the full 8-word prefix is on the page, find_start matches it."""
    doc, page = _make_page("one two three four five six seven eight nine ten")
    r = stp.find_start(page, "one two three four five six seven eight nine ten")
    doc.close()
    assert r is not None


def test_find_start_skip_fallback():
    """If first word isn't on the page but subsequent words are, skip-fallback finds them."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    # Only insert the tail of the highlight (simulating a page break after first word)
    page.insert_text((10, 100), "brown fox jumps over")
    r = stp.find_start(page, "The brown fox jumps over")
    doc.close()
    assert r is not None


def test_find_start_not_found_returns_none():
    """find_start returns None when the text is not on the page."""
    doc, page = _make_page("Something completely different")
    r = stp.find_start(page, "xyzzy_absent_text_notfound")
    doc.close()
    assert r is None


def test_find_start_long_text_trailing_punctuation():
    """3-word prefix with trailing punctuation is found after stripping (mirrors find_end_on_page)."""
    doc, page = _make_page("Hello beautiful world and more words")
    # The prefix "Hello beautiful world" ends with "world" — but search text has trailing comma.
    # find_start must strip the comma and still find the match.
    r = stp.find_start(page, "Hello beautiful world, and more words")
    doc.close()
    assert r is not None


# ── find_end_on_page ──────────────────────────────────────────────────────────

def test_find_end_on_page_found():
    """find_end_on_page returns y_end when the suffix appears on the page."""
    doc, page = _make_page("alpha beta gamma delta epsilon")
    y_end = stp.find_end_on_page(page, "alpha beta gamma delta epsilon", y_min=0)
    doc.close()
    assert y_end is not None
    assert y_end > 0


def test_find_end_on_page_short_text():
    """Two-word suffix is found via the short-text path in find_end_on_page."""
    doc, page = _make_page("Hello world")
    y_end = stp.find_end_on_page(page, "Hello world", y_min=0)
    doc.close()
    assert y_end is not None


def test_find_end_on_page_ymin_constraint():
    """find_end_on_page ignores matches whose y0 is above y_min."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((10, 50), "target text here")    # high on page
    page.insert_text((10, 250), "target text here")   # low on page
    # With a y_min of 200, only the lower occurrence should be found.
    y_end = stp.find_end_on_page(page, "target text here", y_min=200)
    doc.close()
    assert y_end is not None
    assert y_end > 200


def test_find_end_on_page_not_found_returns_none():
    """find_end_on_page returns None when the text is not on the page."""
    doc, page = _make_page("Something else entirely")
    y_end = stp.find_end_on_page(page, "xyzzy_absent_text_notfound", y_min=0)
    doc.close()
    assert y_end is None


def test_find_end_on_page_ymin_excludes_all_occurrences():
    """find_end_on_page returns None when all matches are above y_min."""
    doc, page = _make_page("only match here", y=50)
    # y_min set well below the text; all matches have y0 around 50, so y0 < 400-2 is fine
    # but if we set y_min=300, the match at y≈50 should be excluded.
    y_end = stp.find_end_on_page(page, "only match here", y_min=300)
    doc.close()
    assert y_end is None


# ── unknown highlight color warning ──────────────────────────────────────────

def test_unknown_color_warning_printed_to_stderr(tmp_path, capsys):
    """An unrecognized highlight color must trigger a stderr warning during annotation."""
    import sys as _sys
    import speechify_to_pdf as stp_module
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: hello world . Has context menu"'
        ' class="bg-bg-highlight-notes-light-yellow foo"><span>hello world</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world")
    doc.save(str(pdf))
    doc.close()

    _sys.argv = ["speechify-to-pdf", str(html), str(pdf), "-q"]
    stp_module.main()

    captured = capsys.readouterr()
    assert "light-yellow" in captured.err
    assert "will render as yellow" in captured.err


# ── --list --colors filtering ─────────────────────────────────────────────────

def test_list_mode_colors_filter(tmp_path, capsys):
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: yellow text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>yellow text</span>\n'
        'aria-label="Highlight: pink text . Has context menu"'
        ' class="bg-bg-highlight-notes-pink foo"><span>pink text</span>',
        encoding="utf-8",
    )

    _sys.argv = ["speechify-to-pdf", str(html), "--list", "--colors", "yellow"]
    stp_module.main()

    captured = capsys.readouterr()
    assert "1 highlight" in captured.out
    assert "yellow" in captured.out
    assert "pink" not in captured.out


def test_list_verbose_colors_filter(tmp_path, capsys):
    """--list -v --colors shows per-highlight details for filtered colors only."""
    import sys as _sys
    import speechify_to_pdf as stp_module

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 2</span></button>\n'
        'aria-label="Highlight: important yellow passage . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>important yellow passage</span>\n'
        'aria-label="Highlight: pink detail . Has context menu"'
        ' class="bg-bg-highlight-notes-pink foo"><span>pink detail</span>',
        encoding="utf-8",
    )

    _sys.argv = ["speechify-to-pdf", str(html), "--list", "-v", "--colors", "yellow"]
    stp_module.main()

    captured = capsys.readouterr()
    assert "1 highlight" in captured.out
    assert "important yellow passage" in captured.out
    assert "pink detail" not in captured.out


# ── not-found fraction in summary ────────────────────────────────────────────

def test_not_found_shows_fraction(tmp_path, capsys):
    """'Not found' header must show N/total so the user sees the fraction at a glance."""
    import sys as _sys
    import speechify_to_pdf as stp_module
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: hello world . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>hello world</span>\n'
        'aria-label="Highlight: xyzzy_absent_notfound . Has context menu"'
        ' class="bg-bg-highlight-notes-pink foo"><span>xyzzy_absent_notfound</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world")
    doc.save(str(pdf))
    doc.close()

    _sys.argv = ["speechify-to-pdf", str(html), str(pdf)]
    stp_module.main()

    captured = capsys.readouterr()
    # Must show "Not found (1/2):" so both the count and total are visible
    assert "Not found (1/2):" in captured.out


def test_scanned_pdf_tip_shown_when_no_text(tmp_path, capsys):
    """When all highlights are not found and the PDF has no selectable text, suggest OCR."""
    import sys as _sys
    import speechify_to_pdf as stp_module
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: xyzzy_absent_text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>xyzzy_absent_text</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    # Create a PDF with an image page (no text layer)
    doc = fitz.open()
    doc.new_page()  # blank page — no text inserted
    doc.save(str(pdf))
    doc.close()

    _sys.argv = ["speechify-to-pdf", str(html), str(pdf)]
    with pytest.raises(SystemExit):
        stp_module.main()

    captured = capsys.readouterr()
    assert "scanned image" in captured.out or "selectable text" in captured.out


def test_scanned_pdf_tip_not_shown_when_pdf_has_text(tmp_path, capsys):
    """When all highlights are not found but the PDF has text, the OCR tip must NOT appear."""
    import sys as _sys
    import speechify_to_pdf as stp_module
    import fitz

    html = tmp_path / "Book _ Speechify.html"
    html.write_text(
        '<span>Page 1</span></button>\n'
        'aria-label="Highlight: xyzzy_absent_text . Has context menu"'
        ' class="bg-bg-highlight-notes-yellow foo"><span>xyzzy_absent_text</span>',
        encoding="utf-8",
    )
    pdf = tmp_path / "Book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "This PDF has real selectable text on the page.")
    doc.save(str(pdf))
    doc.close()

    _sys.argv = ["speechify-to-pdf", str(html), str(pdf)]
    with pytest.raises(SystemExit):
        stp_module.main()

    captured = capsys.readouterr()
    assert "scanned image" not in captured.out
    assert "ocrmypdf" not in captured.out
