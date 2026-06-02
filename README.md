# speechify-to-pdf

**Transfer your Speechify highlights directly into your PDF** — as real, standard-compliant PDF annotations, compatible with Citavi, Zotero, Adobe Acrobat, Okular, and every other PDF reader.

[![CI](https://github.com/maun200/speechify_to_pdf/actions/workflows/ci.yml/badge.svg)](https://github.com/maun200/speechify_to_pdf/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/speechify-to-pdf.svg)](https://pypi.org/project/speechify-to-pdf/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![GitHub Stars](https://img.shields.io/github/stars/maun200/speechify_to_pdf?style=social)](https://github.com/maun200/speechify_to_pdf/stargazers)
[![Donate via PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate/?business=m.gruda%40web.de&currency_code=EUR)

> If this tool saves you time, consider buying me a coffee ☕  
> **[➡ Donate via PayPal](https://www.paypal.com/donate/?business=m.gruda%40web.de&currency_code=EUR)**

---

## What it does

Speechify lets you read and highlight PDFs — but your highlights stay locked inside Speechify. This tool extracts them from the saved HTML export and writes them back into your local PDF as proper annotations. Your highlights, your PDF, your reader.

## Installation

### Via pip (recommended)

```bash
pip install speechify-to-pdf
```

This installs the `speechify-to-pdf` command globally.

### Manual

```bash
pip install pymupdf
# then download speechify_to_pdf.py and run it directly
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

### 2. Run the tool

```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf"
```

> **Installed manually?** Replace `speechify-to-pdf` with `python3 speechify_to_pdf.py` in any command below.

This creates `Book_highlights.pdf` in the same folder as the original PDF.

**Custom output path:**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" -o "Book_annotated.pdf"
```

**Print all highlights with details:**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" -v
```

**Auto-detect the PDF (if HTML filename matches):**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html"
```

**Preview without writing any file (dry run):**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" --dry-run
```

**Suppress progress output (useful for scripts/batch processing):**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" -q
```

**Open a password-protected PDF:**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" --password "mysecret"
```

**Fix page offset (e.g. PDF has a 20-page preface Speechify doesn't count):**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" --page-offset 20
```

**Fix page offset for journal articles (PDF pages start above 1, e.g. pages 300–320):**
```bash
speechify-to-pdf "Article _ Speechify.html" "Article.pdf" --page-offset -299
```

**Transfer only specific highlight colors:**
```bash
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" --colors yellow
speechify-to-pdf "Book.pdf _ Speechify.html" "Book.pdf" --colors yellow,pink
```

**Check the version:**
```bash
speechify-to-pdf --version
```

## Example Output

Running the tool on a typical document:

```
$ speechify-to-pdf "Algorithms.pdf _ Speechify.html" "Algorithms.pdf"
HTML:  Algorithms.pdf _ Speechify.html
       17 highlights found
PDF:   Algorithms.pdf  (412 pages)
  Locating: 17/17

  Annotating: 17/17

Result: 16/17 highlights transferred.
Not found (1):
  p.203: This is a very long highlight that starts with the opening words of...

Saved: Algorithms_highlights.pdf
```

With `--verbose`, each highlight is shown as it is placed:

```
$ speechify-to-pdf "Algorithms.pdf _ Speechify.html" "Algorithms.pdf" -v
HTML:  Algorithms.pdf _ Speechify.html
       17 highlights found
PDF:   Algorithms.pdf  (412 pages)
  Locating: 17/17
  ✓ p.12–13 [yellow]: A sorting algorithm is a method for reorganizing a...
  ✓ p.45 [pink] (…): The time complexity of this approach is bounded by...
  ~ p.98 [blue] (end not found, start line only): An invariant must hold at every...
  ✗ p.203 [yellow] NO RECTS: This is a very long highlight that starts with...

Result: 16/17 highlights transferred.
Saved: Algorithms_highlights.pdf
```

Dry run (preview without writing):

```
$ speechify-to-pdf "Algorithms.pdf _ Speechify.html" "Algorithms.pdf" --dry-run
HTML:  Algorithms.pdf _ Speechify.html
       17 highlights found
PDF:   Algorithms.pdf  (412 pages)
  Locating: 17/17

  Annotating: 17/17

Result: 16/17 highlights would be transferred.

Dry run — no file written. Would save to: Algorithms_highlights.pdf
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

- **Truncated texts:** Speechify only shows the first ~80 characters of a long highlight in the sidebar. The tool first tries to recover the full text from the page source (`aria-label` attribute); when successful, the entire highlight is annotated correctly. When only the truncated text (~80 chars) is available, it marks from the start position and estimates the extent.
- **Image pages / scanned PDFs:** On pure image pages without an embedded text layer, no text position can be found (no OCR).
- **Page offset:** The script searches on the indicated page ±2 pages. With larger offsets (e.g. books with long prefaces not counted by Speechify) use `--page-offset N` to shift all lookups by N pages. When many highlights are not found, the tool automatically infers the shift from the ones it did locate and prints a suggested `--page-offset` value.

## Troubleshooting

**"No highlights found"**
→ The sidebar was collapsed during saving. Expand it, reload the page, and save again.

**Many "NOT FOUND"**
→ The HTML and PDF might be from different versions of the book. Or: the PDF contains scanned text without a text layer.
→ If the PDF has unnumbered front matter (cover, preface, TOC) that Speechify does not count, add `--page-offset N`. The tool automatically detects a consistent shift from the highlights it did locate and prints the suggested value.

**`UnicodeDecodeError` when reading the HTML file**
→ Your browser saved the page in a non-UTF-8 encoding. The script automatically falls back to `latin-1`; if you still see errors, re-save the page in your browser and ensure "UTF-8" is selected in the save dialog.

**Highlights appear on the wrong pages (shifted up or down)**
→ The PDF page numbering does not match Speechify's. Use `--page-offset N`:
- Positive N: PDF has front matter (preface, TOC) that Speechify does not count. E.g. `--page-offset 20`.
- Negative N: PDF pages start above 1 (e.g. a journal article numbered pages 300–320). E.g. `--page-offset -299`.
The tool prints a suggested offset automatically when many highlights are missed.

**"PDF is password-protected"**
→ Pass the password with `--password "yourpassword"`. If you don't know the password, decrypt the file first with `qpdf --decrypt input.pdf output.pdf`.

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
