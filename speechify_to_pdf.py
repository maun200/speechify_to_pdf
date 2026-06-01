#!/usr/bin/env python3
"""
speechify_to_pdf.py — Speechify highlights → PDF annotations

Version: 1.2.2

Reads a saved Speechify HTML page ("Save Page As" in browser) and transfers
all highlights as real PDF annotations into the local PDF file.
Highlights are matched exactly: single characters, single lines, and
multi-page spans are all handled correctly.

Usage:
    python3 speechify_to_pdf.py "My Book - Speechify.html" "My Book.pdf"
    python3 speechify_to_pdf.py "My Book - Speechify.html"   # PDF path auto-detected
"""

import argparse
from collections import Counter
import html
import os
import re
import sys
from pathlib import Path

__version__ = "1.2.2"

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Error: PyMuPDF is not installed. Please run: pip install pymupdf")

# ── Colors: Speechify name → PDF-RGB (0..1 each) ───────────────────────────

COLOR_MAP = {
    "yellow": (1.0, 0.93, 0.0),
    "pink":   (1.0, 0.41, 0.71),
    "blue":   (0.4,  0.7,  1.0),
    "green":  (0.4,  0.9,  0.4),
    "orange": (1.0,  0.65, 0.0),
    "purple": (0.7,  0.4,  1.0),
}
DEFAULT_COLOR = (1.0, 0.93, 0.0)

# Page label words across Speechify UI languages (matched case-insensitively)
# Covers: English, French (Page), German (Seite), Spanish/Portuguese (Página),
# Catalan (Pàgina), Italian/Dutch/Romanian (Pagina/Pagine), Korean (페이지),
# Japanese (ページ), Russian/Bulgarian (Страница), Ukrainian (Сторінка), Czech/Slovak (Strana),
# Polish (Strona), Turkish (Sayfa), Traditional Chinese (頁), Simplified Chinese (页),
# Swedish (Sida), Danish/Norwegian (Side), Finnish (Sivu), Hungarian (Oldal),
# Vietnamese (Trang), Arabic (صفحة), Persian/Farsi (صفحه), Hindi (पृष्ठ), Greek (Σελίδα),
# Hebrew (עמוד), Indonesian/Malay (Halaman), Croatian/Serbian (Stranica), Slovenian (Stran),
# Thai (หน้า), Lithuanian (Puslapis), Latvian (Lappuse), Welsh (Tudalen),
# Tagalog/Filipino (Pahina), Azerbaijani (Səhifə), Georgian (გვერდი), Armenian (Էջ),
# Icelandic (Blaðsíða), Estonian (Lehekülg), Basque (Orrialde), Swahili (Ukurasa)
_PAGE_WORDS = r"(?:Page|Seite|Página|Pàgina|Pagina|Pagine|Puslapis|Lappuse|Tudalen|Pahina|Sida|Side|Sivu|Oldal|Trang|Halaman|Stranica|Strana|Strona|Stran|Ukurasa|หน้า|페이지|ページ|[Сс]траница|[Сс]торінка|Sayfa|Σελίδα|頁|页|صفحة|صفحه|पृष्ठ|עמוד|Səhifə|გვერდი|Էջ|Blaðsíða|Lehekülg|Orrialde)"

# Matches whitespace (incl. U+00A0) or any NBSP HTML entity in raw HTML
_WS     = r"(?:[\s ]|&nbsp;|&#160;|&#[Xx]0*[Aa]0;)+"   # one-or-more
_WS_OPT = r"(?:[\s ]|&nbsp;|&#160;|&#[Xx]0*[Aa]0;)*"   # zero-or-more

# Matches decimal, alphanumeric (e.g. "A-1", "B2"), or roman-numeral page numbers.
# [0-9] instead of \d: Python's \d matches Unicode decimal digits (Arabic-Indic,
# Devanagari, etc.) which isdigit() accepts but int() cannot parse, causing a crash.
# Order matters: alphanumeric must come before roman to avoid "D" being parsed as 500.
_PAGE_NUM_PAT = r"[0-9]+|[A-Za-z]-?[0-9]+|[ivxlcdmIVXLCDM]+"
_PAGE_NUM_NC  = r"(?:" + _PAGE_NUM_PAT + ")"     # non-capturing group (for splitting)
_PAGE_NUM     = r"("   + _PAGE_NUM_PAT + ")"     # capturing group (for match.group(1))

# Maximum pages a single highlight is allowed to span during end-search
_MAX_SPAN_PAGES = 8

_ROMAN_MAP = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_TRAILING_PUNCT = ".,;:!?)]}'\"" + "’”"


def _parse_page_num(s: str) -> int:
    if re.match(r'^[0-9]+$', s):
        return int(s)
    # Alphanumeric labels like "A-1", "B2" (appendix pages in some textbooks)
    m = re.match(r'[A-Za-z]-?([0-9]+)$', s)
    if m:
        return int(m.group(1))
    # Roman numerals
    s = s.lower()
    total, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN_MAP.get(ch, 0)
        total += val if val >= prev else -val
        prev = val
    return total


# ── HTML parsing ─────────────────────────────────────────────────────────────

def extract_highlights(html_path: Path) -> list[dict]:
    """
    Returns a list of dicts:
      { page: int, color: str, text: str, note: str|None, truncated: bool }
    'page' is the printed page number from the Speechify sidebar.

    The aria-label attribute often contains the full highlight text even when
    the visible span is truncated for display. We prefer it when it is longer.
    """
    try:
        content = html_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            # cp1252 decodes Windows-specific characters (smart quotes, em dashes,
            # euro sign) in the 0x80-0x9F range that latin-1 would render as
            # control characters.
            content = html_path.read_text(encoding="cp1252")
        except UnicodeDecodeError:
            content = html_path.read_text(encoding="latin-1")
    sections = re.split(
        rf"(?={_PAGE_WORDS}{_WS}{_PAGE_NUM_NC}{_WS_OPT}</span>[\s\S]*?</button>)",
        content, flags=re.IGNORECASE,
    )

    highlights = []
    for section in sections:
        page_m = re.match(rf"{_PAGE_WORDS}{_WS}{_PAGE_NUM}", section, re.IGNORECASE)
        if not page_m:
            continue
        page_num = _parse_page_num(page_m.group(1))

        blocks = re.findall(
            r'aria-label="Highlight: (.*?)(?:\. Note: (.*?))?\s*\.\s*Has context menu"'
            r".*?"
            r'bg-bg-highlight-notes-(\w+)[^"]*"[^>]*>(.*?)</span>',
            section,
            re.DOTALL,
        )

        for aria_raw, note_raw, color, span_html in blocks:
            span_text = re.sub(r"<[^>]+>", "", span_html).strip()
            span_text = html.unescape(re.sub(r"\s+", " ", span_text))

            aria_text = html.unescape(re.sub(r"\s+", " ", aria_raw).strip())

            # Prefer aria-label when it is longer: it sometimes contains the
            # full text while the visible span is truncated at ~80 chars.
            if aria_text and len(aria_text) > len(span_text):
                primary = aria_text
            else:
                primary = span_text

            truncated = primary.endswith("...") or primary.endswith("…")
            search_text = primary.rstrip(".…").strip() if truncated else primary
            note = html.unescape(re.sub(r"\s+", " ", note_raw).strip()) if note_raw else None

            highlights.append({
                "page":      page_num,
                "color":     color,
                "text":      search_text,
                "note":      note,
                "truncated": truncated,
            })

    return highlights


# ── Line rect helpers ─────────────────────────────────────────────────────────

def _collect_lines(page: fitz.Page, y_start: float, y_end: float) -> list[fitz.Rect]:
    """
    Return one merged Rect per text line on `page` whose words fall within
    [y_start, y_end]. Words within 3 pt of each other share a line bucket.
    """
    lines: list[tuple[float, fitz.Rect]] = []  # (representative y0, merged rect)
    for w in page.get_text("words"):
        x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
        if y0 < y_start - 2 or y1 > y_end + 2:
            continue
        r = fitz.Rect(x0, y0, x1, y1)
        merged = False
        for i, (ly0, lr) in enumerate(lines):
            if abs(y0 - ly0) < 3:
                lines[i] = (ly0, lr | r)
                merged = True
                break
        if not merged:
            lines.append((y0, r))
    return [r for _, r in sorted(lines, key=lambda t: t[0])]


def _page_bottom(page: fitz.Page) -> float:
    return page.rect.height - 30


def _detect_page_offset(located: list, current_offset: int) -> int | None:
    """
    Infer a consistent page-offset from successfully located highlights.
    Returns a suggested offset when the majority of found highlights agree on
    a shift that differs from current_offset; otherwise returns None.
    """
    found_offsets = [fp - (h["page"] - 1) for fp, _, h in located if fp is not None]
    if not found_offsets:
        return None
    common_offset, count = Counter(found_offsets).most_common(1)[0]
    if common_offset != current_offset and count >= max(1, len(found_offsets) // 2):
        return common_offset
    return None


# ── Start-position search ────────────────────────────────────────────────────

def find_start(page: fitz.Page, text: str) -> fitz.Rect | None:
    """
    Locate the first occurrence of the beginning of `text` on `page`.
    Tries progressively shorter word-prefixes to handle hyphenation.
    Returns the rect of the first matching fragment, or None.
    """
    words = text.split()

    # Very short text: direct search
    if len(words) <= 2:
        stripped = text.rstrip(_TRAILING_PUNCT)
        for query in dict.fromkeys([text, stripped]):
            hits = page.search_for(query)
            if hits:
                return hits[0]
        return None

    # Prefix search: longest match wins, stops at 3 words
    for n in range(min(8, len(words)), 2, -1):
        hits = page.search_for(" ".join(words[:n]))
        if hits:
            return hits[0]

    # Fallback: skip leading word(s) to dodge orphaned hyphens.
    # Stop at n=2 (inclusive) so 3-word texts get a 2-word substring try —
    # mirroring find_end_on_page which already uses range(..., 1, -1).
    for skip in range(1, min(4, len(words))):
        for n in range(min(7, len(words) - skip), 1, -1):
            hits = page.search_for(" ".join(words[skip:skip + n]))
            if hits:
                return hits[0]

    return None


# ── End-position search (single page) ───────────────────────────────────────

def find_end_on_page(
    page: fitz.Page, text: str, y_min: float
) -> float | None:
    """
    Search for the end of `text` on `page`, only accepting matches at or
    below `y_min`. Returns y_end (bottom of last matching rect), or None.
    """
    words = text.split()

    # Very short text: direct search (mirrors find_start's short-text path).
    # The range loop below never tries n=1, so single-word texts must be
    # handled here to avoid always falling back to "start line only".
    if len(words) <= 2:
        stripped = text.rstrip(_TRAILING_PUNCT)
        for query in dict.fromkeys([text, stripped]):
            for r in page.search_for(query):
                if r.y0 >= y_min - 2:
                    return r.y1
        return None

    for n in range(min(8, len(words)), 1, -1):
        suffix = " ".join(words[-n:])
        stripped = suffix.rstrip(_TRAILING_PUNCT)
        for query in dict.fromkeys([suffix, stripped]):
            for r in page.search_for(query):
                if r.y0 >= y_min - 2:
                    return r.y1
    return None


# ── Rect validation & safe annotation ────────────────────────────────────────

def _valid_rects(page: fitz.Page, rects: list[fitz.Rect]) -> list[fitz.Rect]:
    """Drop zero-area or out-of-bounds rects that make add_highlight_annot crash."""
    clip = page.rect
    result = []
    for r in rects:
        clipped = r & clip
        if clipped.is_valid and not clipped.is_empty and clipped.width > 0.5 and clipped.height > 0.5:
            result.append(clipped)
    return result


def _safe_highlight(page: fitz.Page, rects: list[fitz.Rect], color: tuple, note: str | None) -> bool:
    """Add a highlight annotation safely; returns True on success."""
    valid = _valid_rects(page, rects)
    if not valid:
        return False
    try:
        annot = page.add_highlight_annot(valid)
        annot.set_colors(stroke=color)
        if note:
            annot.set_info(content=note)
        annot.update()
        return True
    except Exception:
        return False


# ── Multi-page annotation ────────────────────────────────────────────────────

def annotate_span(
    doc: fitz.Document,
    start_page: int, y_start: float,
    end_page: int,   y_end: float,
    color: tuple,
    note: str | None,
) -> bool:
    """
    Add highlight annotations from (start_page, y_start) to (end_page, y_end),
    spanning as many pages as needed. Returns True if any annotation was added.
    """
    added = False
    for p in range(start_page, end_page + 1):
        page = doc[p]
        top    = y_start if p == start_page else 0.0
        bottom = y_end   if p == end_page   else _page_bottom(page)
        rects  = _collect_lines(page, top, bottom)
        if _safe_highlight(page, rects, color, note if p == start_page else None):
            added = True
    return added


# ── Complete-highlight placement (with multi-page support) ───────────────────

def place_complete(
    doc: fitz.Document,
    start_page: int, start_rect: fitz.Rect,
    text: str,
    color: tuple, color_name: str, note: str | None,
    verbose: bool,
) -> bool:
    """
    Place a complete (non-truncated) highlight whose full text is known.
    Searches for the end across up to _MAX_SPAN_PAGES pages forward.
    """
    y_start = start_rect.y0

    # Try to find the end on the start page first, then on later pages
    for end_page in range(start_page, min(start_page + _MAX_SPAN_PAGES, doc.page_count)):
        y_min = y_start if end_page == start_page else 0.0
        y_end = find_end_on_page(doc[end_page], text, y_min)
        if y_end is not None:
            ok = annotate_span(doc, start_page, y_start, end_page, y_end, color, note)
            if verbose and ok:
                span = f"p.{start_page+1}" if end_page == start_page else f"p.{start_page+1}–{end_page+1}"
                note_tag = " [+note]" if note else ""
                print(f"  ✓ {span} [{color_name}]{note_tag}: {text[:55]}")
            return ok

    # End not found: fall back to start line only
    rects = _collect_lines(doc[start_page], y_start, start_rect.y1 + 2)
    if _safe_highlight(doc[start_page], rects, color, note):
        if verbose:
            note_tag = " [+note]" if note else ""
            print(f"  ~ p.{start_page+1} [{color_name}]{note_tag} (end not found, start line only): {text[:55]}")
        return True
    return False


# ── Truncated-highlight placement ────────────────────────────────────────────

def place_truncated(
    doc: fitz.Document,
    start_page: int, y_start: float,
    line_height: float,
    next_y_same_page: float | None,
    color: tuple, color_name: str, note: str | None,
    verbose: bool,
    label: str,
) -> bool:
    """
    Place a truncated highlight where only the first ~80 chars are known.
    Caps at the next highlight's start or at 8 lines, whichever is smaller.
    """
    y_cap = y_start + line_height * 8
    # Only use next_y as cap if it is actually below the current highlight
    # (rare edge case: footnotes or sidebars can place a later highlight above)
    if next_y_same_page is not None and next_y_same_page > y_start:
        y_end = min(next_y_same_page, y_cap)
    else:
        y_end = y_cap
    rects = _collect_lines(doc[start_page], y_start, y_end)
    if _safe_highlight(doc[start_page], rects, color, note):
        if verbose:
            note_tag = " [+note]" if note else ""
            print(f"  ✓ p.{start_page+1} [{color_name}]{note_tag} (…): {label[:55]}")
        return True
    return False


# ── Guess PDF path from HTML filename ────────────────────────────────────────

def _iter_pdfs(d: Path, max_depth: int = 3):
    """Yield .pdf paths under d, stopping recursion at max_depth to avoid hangs."""
    for root, dirs, files in os.walk(d):
        depth = len(Path(root).relative_to(d).parts)
        dirs[:] = [] if depth >= max_depth else [s for s in dirs if not s.startswith('.')]
        for f in files:
            if f.lower().endswith(".pdf"):
                yield Path(root) / f


def _expected_pdf_name(html_path: Path) -> str:
    """Return the PDF filename that corresponds to a Speechify HTML export path."""
    name = re.sub(r"\s*[-_|–—]\s*Speechify(\s*\(\d+\))?\s*$", "", html_path.stem, flags=re.IGNORECASE).strip()
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def guess_pdf_path(html_path: Path) -> Path | None:
    pdf_name_stem = _expected_pdf_name(html_path)

    xdg_docs      = os.environ.get("XDG_DOCUMENTS_DIR")
    xdg_downloads = os.environ.get("XDG_DOWNLOAD_DIR")
    xdg_desktop   = os.environ.get("XDG_DESKTOP_DIR")
    search_dirs = [
        html_path.parent,
        html_path.parent.parent,
        Path.cwd(),
        *([ Path(xdg_docs).expanduser() ]      if xdg_docs      else []),
        *([ Path(xdg_downloads).expanduser() ] if xdg_downloads else []),
        *([ Path(xdg_desktop).expanduser() ]   if xdg_desktop   else []),
        Path.home() / "Documents",
        Path.home() / "Dokumente",               # German
        Path.home() / "Documentos",              # Spanish / Portuguese
        Path.home() / "Documenti",               # Italian
        Path.home() / "Documenten",              # Dutch
        Path.home() / "Dokumenty",               # Polish / Czech / Slovak
        Path.home() / "Dokument",                # Swedish
        Path.home() / "Dokumenter",              # Danish / Norwegian
        Path.home() / "Документы",               # Russian / Bulgarian
        Path.home() / "Документи",               # Ukrainian
        Path.home() / "Belgeler",                # Turkish
        Path.home() / "Asiakirjat",              # Finnish
        Path.home() / "Dokumentumok",            # Hungarian
        Path.home() / "Έγγραφα",                 # Greek
        Path.home() / "문서",                    # Korean
        Path.home() / "書類",                    # Japanese (macOS)
        Path.home() / "ドキュメント",             # Japanese (Windows)
        Path.home() / "文件",                    # Traditional Chinese
        Path.home() / "文档",                    # Simplified Chinese
        Path.home() / "Desktop",
        Path.home() / "Schreibtisch",            # German
        Path.home() / "Bureau",                  # French
        Path.home() / "Escritorio",              # Spanish
        Path.home() / "Scrivania",               # Italian
        Path.home() / "Bureaublad",              # Dutch
        Path.home() / "Skrivbord",               # Swedish
        Path.home() / "Skrivebord",              # Danish / Norwegian
        Path.home() / "Pulpit",                  # Polish
        Path.home() / "Рабочий стол",            # Russian / Bulgarian
        Path.home() / "桌面",                    # Chinese (Simplified & Traditional, macOS/Windows)
        Path.home() / "デスクトップ",             # Japanese (macOS/Windows)
        Path.home() / "바탕화면",                # Korean (Windows)
        Path.home() / "바탕 화면",               # Korean (macOS)
        Path.home() / "Downloads",
        Path.home() / "Téléchargements",         # French
        Path.home() / "下载",                    # Simplified Chinese
        Path.home() / "下載",                    # Traditional Chinese
        Path.home() / "ダウンロード",             # Japanese
        Path.home() / "다운로드",                # Korean
        Path.home() / "OneDrive" / "Documents",  # Windows OneDrive
        Path.home() / "OneDrive",                # Windows OneDrive root
        Path.home() / "Dropbox",                 # Dropbox
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs",  # iCloud Drive (macOS)
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents",  # iCloud Documents sync (macOS)
        Path.home() / "iCloudDrive",                                          # iCloud Drive (Windows, iCloud for Windows 12+)
        Path.home() / "My Drive",                # Google Drive for Desktop (Windows/Linux default)
        Path.home() / "Google Drive",            # Google Drive (legacy client)
        # Google Drive for Desktop (macOS 2021+): ~/Library/CloudStorage/GoogleDrive-{email}/My Drive
        *([p / "My Drive"
           for p in sorted((Path.home() / "Library" / "CloudStorage").glob("GoogleDrive-*"))
           if (p / "My Drive").is_dir()]
          if (Path.home() / "Library" / "CloudStorage").exists() else []),
        # OneDrive on macOS (CloudStorage mount): ~/Library/CloudStorage/OneDrive-Personal/ or OneDrive-{org}/
        *([p
           for p in sorted((Path.home() / "Library" / "CloudStorage").glob("OneDrive-*"))
           if p.is_dir()]
          if (Path.home() / "Library" / "CloudStorage").exists() else []),
    ]
    seen: set[Path] = set()
    for d in search_dirs:
        if not d.exists():
            continue
        resolved = d.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        direct = d / pdf_name_stem
        if direct.is_file():
            return direct
        for candidate in _iter_pdfs(d):
            if candidate.name.lower() == pdf_name_stem.lower():
                return candidate

    # Last-resort: direct check in home directory without recursion (avoids
    # scanning the entire home tree which could be huge).
    home = Path.home()
    if home.exists():
        home_resolved = home.resolve()
        if home_resolved not in seen:
            direct = home / pdf_name_stem
            if direct.is_file():
                return direct
            for f in home.iterdir():
                if f.is_file() and f.name.lower() == pdf_name_stem.lower():
                    return f
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transfer Speechify highlights as annotations into a local PDF file."
    )
    parser.add_argument("html", help="Saved Speechify HTML file")
    parser.add_argument("pdf",  nargs="?", help="Local PDF file (optional, auto-detected if omitted)")
    parser.add_argument("-o", "--output", help="Output file (default: <pdf-name>_highlights.pdf)")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Print all highlights with details")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output; only print result and errors")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing output file")
    parser.add_argument("--password", metavar="PASSWORD", help="Password for encrypted/password-protected PDFs")
    parser.add_argument("--page-offset", type=int, default=0, metavar="N",
                        help="Shift all page lookups by N pages (e.g. 20 if the PDF has a 20-page preface not counted by Speechify)")
    parser.add_argument("--colors", metavar="COLOR[,COLOR...]",
                        help="Only transfer highlights of the specified color(s), comma-separated "
                             "(e.g. --colors yellow,pink). Valid colors: " + ", ".join(sorted(COLOR_MAP)))
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.exists():
        sys.exit(f"HTML file not found: {html_path}")

    if args.pdf:
        pdf_path = Path(args.pdf).expanduser().resolve()
    else:
        pdf_path = guess_pdf_path(html_path)
        if not pdf_path:
            sys.exit(
                "Could not auto-detect PDF file.\n"
                f"Expected to find: '{_expected_pdf_name(html_path)}'\n"
                f"Please specify it explicitly: {parser.prog} <html> <pdf>"
            )
        if not args.quiet:
            print(f"PDF auto-detected: {pdf_path}")

    if not pdf_path.exists():
        sys.exit(f"PDF file not found: {pdf_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else pdf_path.parent / (pdf_path.stem + "_highlights.pdf")
    )

    if output_path == pdf_path:
        default_out = pdf_path.parent / (pdf_path.stem + "_highlights.pdf")
        sys.exit(
            f"Error: output path is the same as the input PDF — this would overwrite your original.\n"
            f"Omit -o to use the default output: {default_out}"
        )

    if output_path == html_path:
        sys.exit(
            f"Error: output path is the same as the input HTML file — this would overwrite your source.\n"
            f"Please choose a different output path."
        )

    if not args.dry_run:
        if not output_path.parent.exists():
            sys.exit(f"Error: output directory does not exist: {output_path.parent}")
        if not os.access(output_path.parent, os.W_OK):
            sys.exit(f"Error: output directory is not writable: {output_path.parent}")

    color_filter: set[str] | None = None
    if args.colors:
        color_filter = {c.strip().lower() for c in args.colors.split(",")}
        invalid = color_filter - set(COLOR_MAP)
        if invalid:
            sys.exit(f"Error: unknown color(s): {', '.join(sorted(invalid))}. Valid colors: {', '.join(sorted(COLOR_MAP))}")

    if not args.quiet:
        print(f"HTML:  {html_path.name}")
    highlights = extract_highlights(html_path)
    if not highlights:
        sys.exit(
            "No highlights found.\n"
            "  • Was the highlights sidebar visible when you saved the page?\n"
            "    Expand it (icon in the top-left), then save again with File → Save Page As.\n"
            "  • Did you save as 'Webpage, Complete' (not 'HTML only')?\n"
            "  • Is the correct HTML file specified?"
        )

    if color_filter is not None:
        available_colors = {h["color"] for h in highlights}
        highlights = [h for h in highlights if h["color"] in color_filter]
        if not highlights:
            available = ", ".join(sorted(available_colors)) if available_colors else "(none)"
            sys.exit(
                f"No highlights found matching color(s): {', '.join(sorted(color_filter))}.\n"
                f"Colors present in this document: {available}"
            )
        if not args.quiet:
            print(f"       (filtered to: {', '.join(sorted(color_filter))})")

    if not args.quiet:
        color_counts = Counter(h["color"] for h in highlights)
        if len(color_counts) > 1:
            breakdown = ", ".join(
                f"{n} {c}" for c, n in sorted(color_counts.items(), key=lambda x: -x[1])
            )
            print(f"       {len(highlights)} highlights found ({breakdown})")
        else:
            print(f"       {len(highlights)} highlights found")

    unknown_colors = sorted({h["color"] for h in highlights if h["color"] not in COLOR_MAP})
    for uc in unknown_colors:
        print(f"Warning: unknown highlight color '{uc}' — will render as yellow", file=sys.stderr)

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        sys.exit(f"Error: could not open PDF '{pdf_path.name}': {exc}")
    if doc.is_encrypted:
        if not doc.authenticate(args.password or ""):
            doc.close()
            hint = "Wrong password.\n" if args.password else ""
            sys.exit(
                f"PDF is password-protected: {pdf_path.name}\n"
                f"{hint}Pass --password PASSWORD, or decrypt first (e.g. qpdf --decrypt)."
            )
    if not args.quiet:
        print(f"PDF:   {pdf_path.name}  ({doc.page_count} pages)")

    # ── Pass 1: locate start position of each highlight ──────────────────────
    # Search page hint ±2 pages; record (page_idx, start_rect) or (None, None).
    located: list[tuple[int | None, fitz.Rect | None, dict]] = []
    total = len(highlights)
    is_tty = sys.stdout.isatty()

    for idx, h in enumerate(highlights, 1):
        target = h["page"] - 1 + args.page_offset
        search_order = [target + d for d in [0, -1, 1, -2, 2]
                        if 0 <= target + d < doc.page_count]

        found_page, found_rect = None, None
        for page_idx in search_order:
            r = find_start(doc[page_idx], h["text"])
            if r is not None:
                found_page = page_idx
                found_rect = r
                break

        located.append((found_page, found_rect, h))
        if not args.quiet and is_tty:
            print(f"\r  Locating: {idx}/{total}", end="", flush=True)

    if not args.quiet and is_tty:
        print()  # newline after \r-based progress
    elif not args.quiet:
        print(f"  Locating: {total}/{total}")
    if not args.quiet:
        print()  # blank separator before annotating output

    # ── Pass 2: annotate ─────────────────────────────────────────────────────
    done, not_found = 0, []

    for i, (page_idx, start_rect, h) in enumerate(located):
        if page_idx is None:
            not_found.append(h)
            if args.verbose:
                note_tag = " [+note]" if h["note"] else ""
                trunc_tag = " (…)" if h["truncated"] else ""
                page_info = (f"p.{h['page']} (PDF p.{h['page'] + args.page_offset}±2)"
                             if args.page_offset else f"p.{h['page']}")
                print(f"  ✗ {page_info} [{h['color']}]{note_tag}{trunc_tag} NOT FOUND: {h['text'][:60]}")
            continue

        color = COLOR_MAP.get(h["color"], DEFAULT_COLOR)

        if not h["truncated"]:
            ok = place_complete(
                doc, page_idx, start_rect,
                h["text"], color, h["color"], h["note"], args.verbose,
            )
        else:
            # Truncated: find the next highlight on the same page for y_end hint
            line_h = start_rect.y1 - start_rect.y0 or 12
            next_y: float | None = None
            for j in range(i + 1, len(located)):
                np, nr, _ = located[j]
                if np == page_idx and nr is not None:
                    next_y = nr.y0
                    break

            ok = place_truncated(
                doc, page_idx, start_rect.y0,
                line_h, next_y, color, h["color"], h["note"], args.verbose,
                h["text"],
            )

        if ok:
            done += 1
        else:
            not_found.append(h)
            if args.verbose:
                note_tag = " [+note]" if h["note"] else ""
                trunc_tag = " (…)" if h["truncated"] else ""
                print(f"  ✗ p.{page_idx+1} [{h['color']}]{note_tag}{trunc_tag} NO RECTS: {h['text'][:60]}")
        if not args.verbose and not args.quiet and is_tty:
            print(f"\r  Annotating: {i+1}/{total}", end="", flush=True)

    if not args.verbose and not args.quiet and is_tty:
        print()  # newline after \r-based progress
    elif not args.verbose and not args.quiet:
        print(f"  Annotating: {total}/{total}")
    if not args.quiet:
        print()  # blank line separator before Result
    action = "would be transferred" if args.dry_run else "transferred"
    total = len(highlights)
    s = "" if total == 1 else "s"
    print(f"Result: {done}/{total} highlight{s} {action}.")
    _NOT_FOUND_LIMIT = 10
    if not_found:
        print(f"Not found ({len(not_found)}):")
        for h in not_found[:_NOT_FOUND_LIMIT]:
            page_info = (f"p.{h['page']} (PDF p.{h['page'] + args.page_offset}±2)"
                         if args.page_offset else f"p.{h['page']}")
            note_tag = " [+note]" if h["note"] else ""
            trunc_tag = " (…)" if h["truncated"] else ""
            print(f"  {page_info} [{h['color']}]{note_tag}{trunc_tag}: {h['text'][:80]}")
        if len(not_found) > _NOT_FOUND_LIMIT:
            print(f"  … and {len(not_found) - _NOT_FOUND_LIMIT} more.")
        if len(not_found) >= max(1, len(highlights) // 4):
            detected = _detect_page_offset(located, args.page_offset)
            if detected is not None:
                print(
                    f"\nTip: many highlights were not found. A consistent page shift of "
                    f"{detected} was detected from the located highlights — "
                    f"try --page-offset {detected}."
                )
            elif not args.page_offset:
                print(
                    "\nTip: many highlights were not found. If your PDF has unnumbered front "
                    "matter (cover, preface, TOC) that Speechify does not count, try "
                    "--page-offset N (e.g. --page-offset 20)."
                )
            else:
                print(
                    f"\nTip: many highlights were not found even with --page-offset {args.page_offset}. "
                    "Try adjusting the offset — increase it if highlights appear too early, "
                    "decrease it if they appear too late."
                )
    if not_found and not args.verbose and not args.quiet:
        print("\nTip: run again with -v/--verbose to see per-highlight match details.")

    if done == 0 and not args.dry_run:
        doc.close()
        sys.exit("No highlights were transferred — output file not written.")

    if args.dry_run:
        doc.close()
        if done == 0:
            if not args.quiet:
                print("\nDry run — no file written. No highlights would be transferred.")
        else:
            exists_note = " (would overwrite existing file)" if output_path.exists() else ""
            if not output_path.parent.exists():
                print(f"Warning: output directory does not exist: {output_path.parent}", file=sys.stderr)
            if not args.quiet:
                print(f"\nDry run — no file written. Would save to: {output_path}{exists_note}")
    else:
        if output_path.exists():
            print(f"Warning: overwriting existing output file: {output_path.name}", file=sys.stderr)
        # garbage=0: skip xref rebuild — DRM PDFs have intentionally broken
        # xref tables that garbage=4 would corrupt on re-save.
        try:
            doc.save(output_path, garbage=0, deflate=True)
        except Exception as exc:
            doc.close()
            sys.exit(f"Error: could not save output PDF '{output_path}': {exc}")
        doc.close()
        print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
