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

SEARCH_PREFIX_LEN = 80  # Zeichen für primären Suchstring

# ── HTML parsen ──────────────────────────────────────────────────────────────

def extract_highlights(html_path: Path) -> list[dict]:
    """
    Gibt eine Liste von Dicts zurück:
      { page: int, color: str, text: str, note: str|None, truncated: bool }
    'page' ist die gedruckte Seitennummer aus der Speechify-Sidebar.
    """
    content = html_path.read_text(encoding="utf-8")

    # Jede "Seite X"-Sektion der Sidebar enthält die Highlights dieser Seite
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

            highlights.append(
                {
                    "page":      page_num,
                    "color":     color,
                    "text":      search_text,
                    "note":      note,
                    "truncated": truncated,
                }
            )

    return highlights


# ── Textsuche ────────────────────────────────────────────────────────────────

def find_text_rects(page: fitz.Page, search_text: str, truncated: bool) -> list[fitz.Rect]:
    """
    Sucht den Text auf der Seite und gibt Rechtecke aller gefundenen Zeilen zurück.
    Für vollständige Texte wird der gesamte Bereich von Anfang bis Ende abgedeckt.
    """
    prefix = search_text[:SEARCH_PREFIX_LEN]
    rects = page.search_for(prefix)

    if rects:
        if truncated:
            return rects
        # Vollständiger Text: Zeilen von erstem bis letztem Fundort ermitteln
        suffix = search_text[-SEARCH_PREFIX_LEN:] if len(search_text) > SEARCH_PREFIX_LEN else search_text
        end_rects = page.search_for(suffix)
        if end_rects and end_rects[-1].y1 >= rects[0].y0:
            y_start = rects[0].y0
            y_end   = end_rects[-1].y1
            words   = page.get_text("words")
            line_map: dict[float, fitz.Rect] = {}
            for w in words:
                x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                if y0 >= y_start - 2 and y1 <= y_end + 2:
                    key = round(y0, 1)
                    r   = fitz.Rect(x0, y0, x1, y1)
                    line_map[key] = line_map[key] | r if key in line_map else r
            return list(line_map.values()) if line_map else rects
        return rects

    # Fallback: progressiv kürzere Fragmente ab dem 2./3. Wort probieren
    # (Speechify schneidet manchmal Anfangszeichen ab; Silbentrennung kann Wörter trennen)
    words = search_text.split()
    for start in range(1, min(4, len(words))):
        for end in range(len(words), start + 2, -1):
            fragment = " ".join(words[start:end])[:50]
            if len(fragment) < 15:
                continue
            rects = page.search_for(fragment)
            if rects:
                return rects

    return []


# ── Annotation einfügen ──────────────────────────────────────────────────────

def add_highlight(page: fitz.Page, rects: list[fitz.Rect], color: tuple, note: str | None):
    annot = page.add_highlight_annot(rects)
    annot.set_colors(stroke=color)
    if note:
        annot.set_info(content=note)
    annot.update()


# ── PDF-Pfad aus HTML-Dateiname ableiten ─────────────────────────────────────

def guess_pdf_path(html_path: Path) -> Path | None:
    """
    Speechify benennt die HTML-Datei: '<PDF-Name> _ Speechify.html'
    Wir suchen die entsprechende PDF-Datei in gängigen Verzeichnissen.
    """
    name = html_path.stem  # z. B. "Buch.pdf _ Speechify"
    pdf_name_stem = re.sub(r"\s*_\s*Speechify$", "", name)  # → "Buch.pdf"
    # Das "Stem" enthält bereits ".pdf" im Namen (Speechify-Eigenart)
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
    parser.add_argument("-v", "--verbose", action="store_true", help="Alle gefundenen Markierungen ausgeben")
    args = parser.parse_args()

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.exists():
        sys.exit(f"HTML-Datei nicht gefunden: {html_path}")

    # PDF bestimmen
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

    output_path = Path(args.output).expanduser().resolve() if args.output else (
        pdf_path.parent / (pdf_path.stem + "_highlights.pdf")
    )

    # Highlights extrahieren
    print(f"Lese:  {html_path.name}")
    highlights = extract_highlights(html_path)
    if not highlights:
        sys.exit("Keine Markierungen gefunden. Ist die richtige HTML-Datei angegeben?")
    print(f"       {len(highlights)} Markierungen gefunden")

    # PDF öffnen und annotieren
    print(f"PDF:   {pdf_path.name}  ({fitz.open(pdf_path).page_count} Seiten)")
    doc = fitz.open(pdf_path)

    found, not_found = 0, []

    for h in highlights:
        color = COLOR_MAP.get(h["color"], DEFAULT_COLOR)
        # Suche auf Zielseite ± 2 Seiten (Puffer für unterschiedliche Seitenoffsets)
        target = h["page"] - 1
        search_order = [target] + [target + d for d in [0, -1, 1, -2, 2] if d != 0]
        search_order = [i for i in search_order if 0 <= i < doc.page_count]

        matched = False
        for page_idx in search_order:
            rects = find_text_rects(doc[page_idx], h["text"], h["truncated"])
            if rects:
                add_highlight(doc[page_idx], rects, color, h["note"])
                found += 1
                matched = True
                if args.verbose:
                    note_str = f" [Notiz: {h['note']}]" if h["note"] else ""
                    trunc    = " (…)" if h["truncated"] else ""
                    print(f"  ✓ S.{h['page']} [{h['color']}]{trunc}{note_str}: {h['text'][:60]}")
                break

        if not matched:
            not_found.append(h)

    # Zusammenfassung
    print(f"\nErgebnis: {found}/{len(highlights)} Markierungen übertragen.")
    if not_found:
        print(f"Nicht gefunden ({len(not_found)}):")
        for h in not_found:
            print(f"  S.{h['page']}: {h['text'][:80]}")

    # Speichern
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    print(f"\nGespeichert: {output_path}")


if __name__ == "__main__":
    main()
