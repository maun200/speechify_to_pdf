# speechify-to-pdf

Überträgt Speechify-Markierungen als echte PDF-Annotationen in die lokale Originaldatei — kompatibel mit Citavi, Zotero, Adobe Acrobat und allen anderen PDF-Readern.

## Voraussetzungen

```bash
pip install pymupdf
```

Python 3.10 oder neuer.

## Kurzanleitung

### 1. Speechify-Seite im Browser speichern

1. Das Dokument in Speechify öffnen (app.speechify.com)
2. Im Browser: **Datei → Seite speichern unter** (oder `Strg+S`)
3. Format wählen: **„Webseite, vollständig"** (nicht nur HTML)
4. Gespeichert wird z. B.:
   ```
   Buch.pdf _ Speechify.html
   Buch.pdf _ Speechify_files/   ← Ordner muss daneben liegen
   ```

> **Hinweis:** Die Seitenleiste mit den Markierungen muss sichtbar sein, wenn du speicherst. Falls sie eingeklappt ist, aufklappen (Symbol oben links) und erneut speichern.

### 2. Script ausführen

```bash
python3 speechify_to_pdf.py "Buch.pdf _ Speechify.html" "Buch.pdf"
```

Das erzeugt `Buch_highlights.pdf` im selben Ordner wie die Originaldatei.

Eigenen Ausgabepfad festlegen:

```bash
python3 speechify_to_pdf.py "Buch.pdf _ Speechify.html" "Buch.pdf" -o "Buch_annotiert.pdf"
```

Alle Markierungen einzeln ausgeben:

```bash
python3 speechify_to_pdf.py "Buch.pdf _ Speechify.html" "Buch.pdf" -v
```

## Was wird übertragen?

| Speechify-Element | PDF-Annotation |
|---|---|
| Gelbe Markierung | Gelbes Highlight |
| Pinke Markierung | Pinkes Highlight |
| Notiz zur Markierung | Kommentar an der Annotation |
| Seitennummer | Korrekte PDF-Seite (±2 Seiten Toleranz) |

## Einschränkungen

- **Abgeschnittene Texte:** Speechify zeigt in der Seitenleiste nur die ersten ~80 Zeichen eines langen Highlights. Das Script markiert in diesem Fall nur den sichtbaren Anfang — der Rest der Passage bleibt unmarkiert. Der Volltext ist in der gespeicherten HTML leider nicht vorhanden.
- **Bildseiten / gescannte PDFs:** Auf reinen Bildseiten ohne eingebetteten Text kann keine Textposition gefunden werden (kein OCR).
- **Seitenoffset:** Das Script sucht auf der angegebenen Seite ± 2 Seiten. Bei ungewöhnlichen Offsets (z. B. Bücher mit langen Vorwörtern) kann es zu vereinzelten Fehlzuordnungen kommen.

## Troubleshooting

**„Keine Markierungen gefunden"**
→ Die Seitenleiste war beim Speichern eingeklappt. Aufklappen, Seite neu laden, erneut speichern.

**Viele „NICHT GEFUNDEN"**
→ HTML und PDF könnten aus unterschiedlichen Versionen des Buches stammen. Oder: die PDF enthält gescannten Text ohne Textlayer.

**`ModuleNotFoundError: No module named 'fitz'`**
→ `pip install pymupdf` ausführen.
