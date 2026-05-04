# speechify-to-pdf

**Transfer your Speechify highlights directly into your PDF** — as real, standard-compliant PDF annotations, compatible with Citavi, Zotero, Adobe Acrobat, Okular, and every other PDF reader.

[![CI](https://github.com/maun200/speechify_to_pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/maun200/speechify_to_pdf/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate/?business=m.gruda%40web.de&currency_code=EUR)

> If this tool saves you time, consider buying me a coffee ☕  
> **[➡ Donate via PayPal](https://www.paypal.com/donate/?business=m.gruda%40web.de&currency_code=EUR)**

---

## What it does

Speechify lets you read and highlight PDFs — but your highlights stay locked inside Speechify. This tool extracts them from the saved HTML export and writes them back into your local PDF as proper annotations. Your highlights, your PDF, your reader.

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

**Custom output path:**
```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf" -o "Book_annotated.pdf"
```

**Print all highlights with details:**
```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html" "Book.pdf" -v
```

**Auto-detect the PDF (if HTML filename matches):**
```bash
python3 speechify_to_pdf.py "Book.pdf _ Speechify.html"
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

## Roadmap

- [ ] GUI (tkinter drag-and-drop) for non-technical users
- [ ] Standalone executable (PyInstaller / `.exe` / `.app`)
- [ ] Support for newer Speechify export formats
- [ ] Batch processing of multiple files

## Contributing

Pull requests and issue reports are welcome!  
Please open an issue before starting work on larger changes.  
See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Related projects

- **[kindle-highlights-to-pdf](https://github.com/maun200/kindle-highlights-to-pdf)** — Same idea for Kindle users: transfer `My Clippings.txt` highlights into your PDF.

## Support the project

This tool is free and open-source. If it saves you time, a small donation helps keep it maintained and improved:

**[☕ Donate via PayPal](https://www.paypal.com/donate/?business=m.gruda%40web.de&currency_code=EUR)**

## License

MIT
