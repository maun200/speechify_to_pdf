#!/usr/bin/env python3
"""
speechify_to_pdf.py — Speechify highlights → PDF annotations

Version: 1.1.0

Reads a saved Speechify HTML page ("Save Page As" in browser) and transfers
all highlights as real PDF annotations into the local PDF file.
Highlights are matched exactly: single characters, single lines, and
multi-page spans are all handled correctly.

Usage:
    python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf"
    python3 speechify_to_pdf.py "Book.pdf _ Speechify.html"   # PDF path auto-detected
"""

import argparse
import html
import re
import sys
from pathlib import Path

__version__ = "1.1.0"

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
_PAGE_WORDS = r"(?:Page|Seite|Página|Pagina|Pagine|페이지|ページ|[Сс]траница|Strana|Strona|Sayfa|頁|页)"

# Matches whitespace (incl. U+00A0) or any NBSP HTML entity in raw HTML
_WS = r"(?:[\s ]|&nbsp;|&#160;|&#[Xx][Aa]0;)+"

# Matches decimal or roman-numeral page numbers (e.g. "42", "xiv", "XIV")
_PAGE_NUM_PAT = r"\d+|[ivxlcdmIVXLCDM]+"        # core alternatives
_PAGE_NUM_NC  = r"(?:" + _PAGE_NUM_PAT + ")"     # non-capturing group (for splitting)
_PAGE_NUM     = r"("   + _PAGE_NUM_PAT + ")"     # capturing group (for match.group(1))

# Maximum pages a single highlight is allowed to span during end-search
_MAX_SPAN_PAGES = 8

_ROMAN_MAP = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _parse_page_num(s: str) -> int:
    if s.isdigit():
        return int(s)
    s = s.lower()
    if not all(c in _ROMAN_MAP for c in s):
        return int(s)
    total, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN_MAP[ch]
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
    content = html_path.read_text(encoding="utf-8")
    sections = re.split(
        rf"(?={_PAGE_WORDS}{_WS}{_PAGE_NUM_NC}\s*</span>\s*</button>)",
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

            truncated = primary.endswith("...")
            search_text = primary.rstrip(".").strip() if truncated else primary
            note = re.sub(r"\s+", " ", note_raw).strip() if note_raw else None

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
        for query in (text, text.rstrip(".,;:")):
            hits = page.search_for(query)
            if hits:
                return hits[0]
        return None

    # Prefix search: longest match wins, stops at 3 words
    for n in range(min(8, len(words)), 2, -1):
        hits = page.search_for(" ".join(words[:n]))
        if hits:
            return hits[0]

    # Fallback: skip leading word(s) to dodge orphaned hyphens
    for skip in range(1, min(4, len(words))):
        for n in range(min(7, len(words) - skip), 2, -1):
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

    for n in range(min(8, len(words)), 1, -1):
        suffix = " ".join(words[-n:])
        for r in page.search_for(suffix):
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
    color: tuple, note: str | None,
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
                print(f"  ✓ {span} [{color}]: {text[:55]}")
            return ok

    # End not found: fall back to start line only
    rects = _collect_lines(doc[start_page], y_start, start_rect.y1 + 2)
    if _safe_highlight(doc[start_page], rects, color, note):
        if verbose:
            print(f"  ~ p.{start_page+1} [{color}] (end not found, start line only): {text[:55]}")
        return True
    return False


# ── Truncated-highlight placement ────────────────────────────────────────────

def place_truncated(
    doc: fitz.Document,
    start_page: int, y_start: float,
    line_height: float,
    next_y_same_page: float | None,
    color: tuple, note: str | None,
    verbose: bool,
    label: str,
) -> bool:
    """
    Place a truncated highlight where only the first ~80 chars are known.
    Caps at the next highlight's start or at 8 lines, whichever is smaller.
    """
    y_cap = y_start + line_height * 8
    y_end = min(next_y_same_page, y_cap) if next_y_same_page is not None else y_cap
    rects = _collect_lines(doc[start_page], y_start, y_end)
    if _safe_highlight(doc[start_page], rects, color, note):
        if verbose:
            print(f"  ✓ p.{start_page+1} [{color}] (…): {label[:55]}")
        return True
    return False


# ── Guess PDF path from HTML filename ────────────────────────────────────────

def guess_pdf_path(html_path: Path) -> Path | None:
    name = html_path.stem
    pdf_name_stem = re.sub(r"\s*_\s*Speechify$", "", name).strip()
    if not pdf_name_stem.lower().endswith(".pdf"):
        pdf_name_stem += ".pdf"

    search_dirs = [
        html_path.parent,
        html_path.parent.parent,
        Path.home() / "Documents",
        Path.home() / "Dokumente",
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for candidate in d.rglob("*.pdf"):
            if candidate.is_file() and candidate.name.lower() == pdf_name_stem.lower():
                return candidate
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transfer Speechify highlights as annotations into a local PDF file."
    )
    parser.add_argument("html", help="Saved Speechify HTML file")
    parser.add_argument("pdf",  nargs="?", help="Local PDF file (optional, auto-detected if omitted)")
    parser.add_argument("-o", "--output", help="Output file (default: <pdf-name>_highlights.pdf)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print all highlights with details")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing output file")
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
                "Please specify it explicitly: speechify_to_pdf.py <html> <pdf>"
            )
        print(f"PDF auto-detected: {pdf_path}")

    if not pdf_path.exists():
        sys.exit(f"PDF file not found: {pdf_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else pdf_path.parent / (pdf_path.stem + "_highlights.pdf")
    )

    print(f"HTML:  {html_path.name}")
    highlights = extract_highlights(html_path)
    if not highlights:
        sys.exit("No highlights found. Is the correct HTML file specified?")
    print(f"       {len(highlights)} highlights found")

    doc = fitz.open(pdf_path)
    if doc.is_encrypted and not doc.authenticate(""):
        doc.close()
        sys.exit(
            f"PDF is password-protected: {pdf_path.name}\n"
            "Please decrypt the file first (e.g. with qpdf --decrypt) and try again."
        )
    print(f"PDF:   {pdf_path.name}  ({doc.page_count} pages)")

    # ── Pass 1: locate start position of each highlight ──────────────────────
    # Search page hint ±2 pages; record (page_idx, start_rect) or (None, None).
    located: list[tuple[int | None, fitz.Rect | None, dict]] = []
    total = len(highlights)

    for idx, h in enumerate(highlights, 1):
        target = h["page"] - 1
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
        print(f"\r  Locating: {idx}/{total}", end="", flush=True)

    print()  # newline after progress

    # ── Pass 2: annotate ─────────────────────────────────────────────────────
    done, not_found = 0, []

    for i, (page_idx, start_rect, h) in enumerate(located):
        if page_idx is None:
            not_found.append(h)
            if args.verbose:
                print(f"  ✗ p.{h['page']} [{h['color']}] NOT FOUND: {h['text'][:60]}")
            continue

        color = COLOR_MAP.get(h["color"], DEFAULT_COLOR)

        if not h["truncated"]:
            ok = place_complete(
                doc, page_idx, start_rect,
                h["text"], color, h["note"], args.verbose,
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
                line_h, next_y, color, h["note"], args.verbose,
                h["text"],
            )

        if ok:
            done += 1
        else:
            not_found.append(h)
            if args.verbose:
                print(f"  ✗ p.{page_idx+1} [{h['color']}] NO RECTS: {h['text'][:60]}")
        print(f"\r  Annotating: {i+1}/{total}", end="", flush=True)

    print()  # newline after progress
    print(f"\nResult: {done}/{len(highlights)} highlights transferred.")
    if not_found:
        print(f"Not found ({len(not_found)}):")
        for h in not_found:
            print(f"  p.{h['page']}: {h['text'][:80]}")

    if args.dry_run:
        doc.close()
        print(f"\nDry run — no file written. Would save to: {output_path}")
    else:
        # garbage=0: skip xref rebuild — DRM PDFs have intentionally broken
        # xref tables that garbage=4 would corrupt on re-save.
        doc.save(output_path, garbage=0, deflate=True)
        doc.close()
        print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
