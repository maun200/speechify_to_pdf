#!/usr/bin/env python3
"""
speechify_to_pdf.py — Speechify highlights → PDF annotations

Reads a saved Speechify HTML page ("Save Page As" in browser) and transfers
all highlights as real PDF annotations into the local PDF file.

Usage:
    python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf"
    python3 speechify_to_pdf.py "Book.pdf _ Speechify.html"   # PDF path auto-detected
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Fehler: PyMuPDF nicht installiert. Bitte ausführen: pip install pymupdf")

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

# Page label words across Speechify UI languages
_PAGE_WORDS = r"(?:Page|Seite|Página|Pagina|Pagine|페이지|ページ|Страница|страница|Strana|Sayfa)"

# ── HTML parsing ─────────────────────────────────────────────────────────────

def extract_highlights(html_path: Path) -> list[dict]:
    """
    Returns a list of dicts:
      { page: int, color: str, text: str, note: str|None, truncated: bool }
    'page' is the printed page number from the Speechify sidebar.
    List is in document order (page ascending, then HTML order).
    """
    content = html_path.read_text(encoding="utf-8")
    sections = re.split(rf"(?={_PAGE_WORDS} \d+</span></button>)", content)

    highlights = []
    for section in sections:
        page_m = re.match(rf"{_PAGE_WORDS} (\d+)", section)
        if not page_m:
            continue
        page_num = int(page_m.group(1))

        blocks = re.findall(
            r'aria-label="Highlight: (.*?)(?:\. Note: (.*?))?\s*\.\s*Has context menu"'
            r".*?"
            r'bg-bg-highlight-notes-(\w+)[^"]*"[^>]*>(.*?)</span>',
            section,
            re.DOTALL,
        )

        for _aria, note_raw, color, span_html in blocks:
            span_text = re.sub(r"<[^>]+>", "", span_html).strip()
            span_text = re.sub(r"\s+", " ", span_text)

            truncated = span_text.endswith("...")
            search_text = span_text.rstrip(".").strip() if truncated else span_text
            note = re.sub(r"\s+", " ", note_raw).strip() if note_raw else None

            highlights.append({
                "page":      page_num,
                "color":     color,
                "text":      search_text,
                "note":      note,
                "truncated": truncated,
            })

    return highlights


# ── Text search ──────────────────────────────────────────────────────────────

def find_start_rects(page: fitz.Page, search_text: str) -> list[fitz.Rect]:
    """
    Finds the start position of text on the page.
    Uses progressively shorter prefixes to work around hyphenation.
    Returns rects of the first found line.
    """
    words_in_text = search_text.split()

    # Kurze Texte (1-2 Wörter): direkt suchen, auch mit/ohne Satzzeichen
    if len(words_in_text) <= 2:
        for query in [search_text, search_text.rstrip(".,;:")]:
            rects = page.search_for(query)
            if rects:
                return [rects[0]]
        return []

    # Versuche Prefixe verschiedener Länge (kurz genug um Silbentrennung zu umgehen)
    for n_words in range(min(8, len(words_in_text)), 2, -1):
        fragment = " ".join(words_in_text[:n_words])
        rects = page.search_for(fragment)
        if rects:
            return [rects[0]]  # Nur erste Fundzeile = Startpunkt

    # Fallback: ab zweitem Wort
    for start in range(1, min(4, len(words_in_text))):
        for n in range(min(7, len(words_in_text) - start), 2, -1):
            fragment = " ".join(words_in_text[start:start + n])
            rects = page.search_for(fragment)
            if rects:
                return [rects[0]]

    return []


def get_rects_in_range(
    page: fitz.Page, y_start: float, y_end: float | None
) -> list[fitz.Rect]:
    """
    Returns word rects of all lines between y_start and y_end.
    y_end=None means until end of page.
    """
    page_bottom = page.rect.height - 30  # unterer Rand freilassen
    if y_end is None:
        y_end = page_bottom

    words = page.get_text("words")  # (x0, y0, x1, y1, word, block_no, line_no, word_no)
    line_map: dict[float, fitz.Rect] = {}

    for w in words:
        x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
        if y0 >= y_start - 2 and y1 <= y_end + 2:
            key = round(y0, 1)
            r = fitz.Rect(x0, y0, x1, y1)
            line_map[key] = line_map[key] | r if key in line_map else r

    return list(line_map.values())


def get_rects_between_texts(
    page: fitz.Page, search_text: str, start_rects: list[fitz.Rect]
) -> list[fitz.Rect]:
    """
    For complete (non-truncated) texts: span from start to end of known text.
    """
    y_start = start_rects[0].y0

    # Suche das Ende via Suffix
    words_in_text = search_text.split()
    end_rects = []
    for n_words in range(min(8, len(words_in_text)), 2, -1):
        fragment = " ".join(words_in_text[-n_words:])
        found = page.search_for(fragment)
        if found and found[-1].y1 >= y_start:
            end_rects = found
            break

    if not end_rects:
        return start_rects

    y_end = end_rects[-1].y1
    return get_rects_in_range(page, y_start, y_end)


# ── Add annotation ───────────────────────────────────────────────────────────

def add_highlight(page: fitz.Page, rects: list[fitz.Rect], color: tuple, note: str | None):
    if not rects:
        return
    annot = page.add_highlight_annot(rects)
    annot.set_colors(stroke=color)
    if note:
        annot.set_info(content=note)
    annot.update()


# ── Guess PDF path from HTML filename ────────────────────────────────────────

def guess_pdf_path(html_path: Path) -> Path | None:
    name = html_path.stem
    pdf_name_stem = re.sub(r"\s*_\s*Speechify$", "", name)
    if not pdf_name_stem.lower().endswith(".pdf"):
        pdf_name_stem += ".pdf"

    search_dirs = [
        html_path.parent,
        html_path.parent.parent,
        Path.home() / "Documents",
        Path.home() / "Dokumente",  # German Windows
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for candidate in d.rglob("*.pdf"):
            if candidate.name.lower() == pdf_name_stem.lower():
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
    print(f"PDF:   {pdf_path.name}  ({doc.page_count} pages)")

    # ── Pass 1: locate start position of each highlight in the PDF ──────────
    # Result: list of (page_idx | None, y_start | None, highlight-dict)
    located: list[tuple[int | None, float | None, dict]] = []

    for h in highlights:
        target = h["page"] - 1
        search_order = [target + d for d in [0, -1, 1, -2, 2] if 0 <= target + d < doc.page_count]

        found_page, found_y = None, None
        for page_idx in search_order:
            rects = find_start_rects(doc[page_idx], h["text"])
            if rects:
                found_page = page_idx
                found_y = rects[0].y0
                break

        located.append((found_page, found_y, h))

    # ── Pass 2: annotate highlights with full rect spans ────────────────────
    done, not_found = 0, []

    for i, (page_idx, y_start, h) in enumerate(located):
        if page_idx is None:
            not_found.append(h)
            if args.verbose:
                print(f"  ✗ p.{h['page']} [{h['color']}] NOT FOUND: {h['text'][:60]}")
            continue

        page  = doc[page_idx]
        color = COLOR_MAP.get(h["color"], DEFAULT_COLOR)

        if not h["truncated"]:
            # Vollständiger Text: Anfang bis Ende des bekannten Textes
            start_rects = find_start_rects(page, h["text"])
            final_rects = get_rects_between_texts(page, h["text"], start_rects)
        else:
            # Abgeschnittener Text: von Startzeile bis Startzeile des nächsten
            # Highlights auf derselben Seite (oder Seitenende)
            y_end = None
            for j in range(i + 1, len(located)):
                next_page, next_y, _ = located[j]
                if next_page == page_idx and next_y is not None:
                    y_end = next_y
                    break

            final_rects = get_rects_in_range(page, y_start, y_end)

        if not final_rects:
            not_found.append(h)
            if args.verbose:
                print(f"  ✗ p.{h['page']} [{h['color']}] NO RECTS: {h['text'][:60]}")
            continue

        add_highlight(page, final_rects, color, h["note"])
        done += 1

        if args.verbose:
            note_str = f" [note: {h['note']}]" if h["note"] else ""
            trunc    = " (…)" if h["truncated"] else ""
            n_lines  = len(final_rects)
            print(f"  ✓ p.{h['page']} [{h['color']}]{trunc}{note_str} {n_lines} lines: {h['text'][:55]}")

    print(f"\nResult: {done}/{len(highlights)} highlights transferred.")
    if not_found:
        print(f"Not found ({len(not_found)}):")
        for h in not_found:
            print(f"  p.{h['page']}: {h['text'][:80]}")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
