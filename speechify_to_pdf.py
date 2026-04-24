#!/usr/bin/env python3
"""
speechify_to_pdf.py — Speechify-Markierungen → PDF-Annotationen

Liest eine gespeicherte Speechify-HTML-Seite ("Speichern unter" im Browser)
und überträgt alle Highlights als echte PDF-Annotationen in die lokale PDF-Datei.

Verwendung:
    python3 speechify_to_pdf.py "Buch.pdf _ Speechify.html" "Buch.pdf"
    python3 speechify_to_pdf.py "Buch.pdf _ Speechify.html"   # PDF-Pfad wird automatisch gesucht
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Fehler: PyMuPDF nicht installiert. Bitte ausführen: pip install pymupdf")

# ── Farben: Speechify-Name → PDF-RGB (je 0..1) ──────────────────────────────

COLOR_MAP = {
    "yellow": (1.0, 0.93, 0.0),
    "pink":   (1.0, 0.41, 0.71),
    "blue":   (0.4,  0.7,  1.0),
    "green":  (0.4,  0.9,  0.4),
    "orange": (1.0,  0.65, 0.0),
    "purple": (0.7,  0.4,  1.0),
}
DEFAULT_COLOR = (1.0, 0.93, 0.0)

# ── HTML parsen ──────────────────────────────────────────────────────────────

def extract_highlights(html_path: Path) -> list[dict]:
    """
    Gibt eine Liste von Dicts zurück:
      { page: int, color: str, text: str, note: str|None, truncated: bool }
    'page' ist die gedruckte Seitennummer aus der Speechify-Sidebar.
    Die Liste ist in Dokumentreihenfolge (Seite aufsteigend, dann Reihenfolge im HTML).
    """
    content = html_path.read_text(encoding="utf-8")
    sections = re.split(r"(?=Seite \d+</span></button>)", content)

    highlights = []
    for section in sections:
        page_m = re.match(r"Seite (\d+)", section)
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


# ── Textsuche ────────────────────────────────────────────────────────────────

def find_start_rects(page: fitz.Page, search_text: str) -> list[fitz.Rect]:
    """
    Sucht den Beginn des Textes auf der Seite.
    Verwendet progressiv kürzere Prefixe um Silbentrennung zu umgehen.
    Gibt die Rects der ersten Fundzeile zurück.
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
    Gibt Word-Rects aller Zeilen zurück, die zwischen y_start und y_end liegen.
    y_end=None bedeutet bis Seitenende.
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
    Für vollständige (nicht abgeschnittene) Texte: span von Anfang bis Ende.
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


# ── Annotation einfügen ──────────────────────────────────────────────────────

def add_highlight(page: fitz.Page, rects: list[fitz.Rect], color: tuple, note: str | None):
    if not rects:
        return
    annot = page.add_highlight_annot(rects)
    annot.set_colors(stroke=color)
    if note:
        annot.set_info(content=note)
    annot.update()


# ── PDF-Pfad aus HTML-Dateiname ableiten ─────────────────────────────────────

def guess_pdf_path(html_path: Path) -> Path | None:
    name = html_path.stem
    pdf_name_stem = re.sub(r"\s*_\s*Speechify$", "", name)
    if not pdf_name_stem.lower().endswith(".pdf"):
        pdf_name_stem += ".pdf"

    search_dirs = [
        html_path.parent,
        html_path.parent.parent,
        Path.home() / "Documents",
        Path.home() / "Dokumente",
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for candidate in d.rglob("*.pdf"):
            if candidate.name.lower() == pdf_name_stem.lower():
                return candidate
    return None


# ── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Überträgt Speechify-Markierungen als Annotationen in eine lokale PDF-Datei."
    )
    parser.add_argument("html", help="Gespeicherte Speechify-HTML-Datei")
    parser.add_argument("pdf",  nargs="?", help="Lokale PDF-Datei (optional, wird sonst gesucht)")
    parser.add_argument("-o", "--output", help="Ausgabedatei (Standard: <pdf-name>_highlights.pdf)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Alle Markierungen mit Details ausgeben")
    args = parser.parse_args()

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.exists():
        sys.exit(f"HTML-Datei nicht gefunden: {html_path}")

    if args.pdf:
        pdf_path = Path(args.pdf).expanduser().resolve()
    else:
        pdf_path = guess_pdf_path(html_path)
        if not pdf_path:
            sys.exit(
                "Konnte PDF-Datei nicht automatisch finden.\n"
                "Bitte explizit angeben: speechify_to_pdf.py <html> <pdf>"
            )
        print(f"PDF automatisch gefunden: {pdf_path}")

    if not pdf_path.exists():
        sys.exit(f"PDF-Datei nicht gefunden: {pdf_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else pdf_path.parent / (pdf_path.stem + "_highlights.pdf")
    )

    # Highlights aus HTML laden
    print(f"Lese:  {html_path.name}")
    highlights = extract_highlights(html_path)
    if not highlights:
        sys.exit("Keine Markierungen gefunden. Ist die richtige HTML-Datei angegeben?")
    print(f"       {len(highlights)} Markierungen gefunden")

    doc = fitz.open(pdf_path)
    print(f"PDF:   {pdf_path.name}  ({doc.page_count} Seiten)")

    # ── Pass 1: Startposition jedes Highlights im PDF finden ────────────────
    # Ergebnis: Liste von (page_idx | None, y_start | None, highlight-dict)
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

    # ── Pass 2: Highlights mit vollständigem Bereich annotieren ─────────────
    done, not_found = 0, []

    for i, (page_idx, y_start, h) in enumerate(located):
        if page_idx is None:
            not_found.append(h)
            if args.verbose:
                print(f"  ✗ S.{h['page']} [{h['color']}] NICHT GEFUNDEN: {h['text'][:60]}")
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
                print(f"  ✗ S.{h['page']} [{h['color']}] KEINE RECTS: {h['text'][:60]}")
            continue

        add_highlight(page, final_rects, color, h["note"])
        done += 1

        if args.verbose:
            note_str = f" [Notiz: {h['note']}]" if h["note"] else ""
            trunc    = " (…)" if h["truncated"] else ""
            n_lines  = len(final_rects)
            print(f"  ✓ S.{h['page']} [{h['color']}]{trunc}{note_str} {n_lines} Zeilen: {h['text'][:55]}")

    # Zusammenfassung
    print(f"\nErgebnis: {done}/{len(highlights)} Markierungen übertragen.")
    if not_found:
        print(f"Nicht gefunden ({len(not_found)}):")
        for h in not_found:
            print(f"  S.{h['page']}: {h['text'][:80]}")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    print(f"\nGespeichert: {output_path}")


if __name__ == "__main__":
    main()
