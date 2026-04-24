# speechify-to-pdf

Transfers Speechify annotations as real PDF annotations into your local original file — compatible with Citavi, Zotero, Adobe Acrobat, and all other PDF readers.

## Requirements

```bash
pip install pymupdf
```

Python 3.10 or newer.

## Quick Start

### 1. Save the Speechify page in your browser

1. Open the document in Speechify (app.speechify.com)
2. In your browser: **File → Save Page As** (or `Ctrl+S`)
3. Choose format: **"Webpage, Complete"** (not HTML only)
4. The result will look like:
   ```
   Book.pdf _ Speechify.html
   Book.pdf _ Speechify_files/   ← folder must be next to the HTML file
   ```

> **Note:** The sidebar with highlights must be visible when you save. If it is collapsed, expand it (icon in the top left) and save again.

### 2. Run the script

```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf"
```

This creates `Book_highlights.pdf` in the same folder as the original PDF.

Set a custom output path:

```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf" -o "Book_annotated.pdf"
```

Print all highlights with details:

```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf" -v
```

## What gets transferred?

| Speechify element | PDF annotation |
|---|---|
| Yellow highlight | Yellow highlight |
| Pink highlight | Pink highlight |
| Blue highlight | Blue highlight |
| Green highlight | Green highlight |
| Orange highlight | Orange highlight |
| Purple highlight | Purple highlight |
| Note on a highlight | Comment on the annotation |
| Page number | Correct PDF page (±2 pages tolerance) |

## Limitations

- **Truncated texts:** Speechify only shows the first ~80 characters of a long highlight in the sidebar. The script marks only the visible beginning — the rest of the passage remains unmarked, as the full text is not available in the saved HTML.
- **Image pages / scanned PDFs:** On pure image pages without an embedded text layer, no text position can be found (no OCR).
- **Page offset:** The script searches on the indicated page ±2 pages. With unusual offsets (e.g. books with long prefaces) there may be occasional mismatches.

## Troubleshooting

**"No highlights found"**
→ The sidebar was collapsed during saving. Expand it, reload the page, and save again.

**Many "NOT FOUND"**
→ The HTML and PDF might be from different versions of the book. Or: the PDF contains scanned text without a text layer.

**`ModuleNotFoundError: No module named 'fitz'`**
→ Run `pip install pymupdf`.

## Contributing

Pull requests and issue reports are welcome! Please open an issue before starting work on larger changes.

## License

MIT
