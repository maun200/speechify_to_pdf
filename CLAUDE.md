# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Single-file Python CLI tool (`speechify_to_pdf.py`) that parses a saved Speechify HTML page and writes highlights + notes as real PDF annotations using PyMuPDF (fitz).

## Commands

```bash
pip install pymupdf                          # install dependency
python3 speechify_to_pdf.py <html> <pdf>    # basic usage
python3 speechify_to_pdf.py <html> <pdf> -v # verbose output
python3 speechify_to_pdf.py <html>          # auto-detect PDF path
```

## Architecture

All logic is in `speechify_to_pdf.py` with four conceptual stages:

1. **HTML parsing** (`extract_highlights`) — splits saved Speechify HTML by page-label buttons (language-aware via `_PAGE_WORDS`), then extracts highlight blocks via regex on `aria-label` and CSS color class attributes.

2. **Text location — Pass 1** (`find_start_rects`) — for each highlight, searches the PDF page (±2 page tolerance) using progressively shorter word prefixes to handle hyphenation edge cases.

3. **Rect expansion — Pass 2** — for complete highlights uses `get_rects_between_texts` (start→end suffix search); for truncated highlights (~80-char Speechify cutoff) uses `get_rects_in_range` from start y to next highlight's y on the same page.

4. **Annotation write** (`add_highlight`) — calls PyMuPDF `add_highlight_annot`, sets color from `COLOR_MAP`, attaches note as annotation content.

## Key constraints

- Speechify's sidebar only exposes the first ~80 characters of long highlights — truncated highlights are detected via trailing `"..."` and handled differently.
- The HTML page-section splitter must match the UI language; `_PAGE_WORDS` covers English, German, Spanish, Italian, French, Japanese, Korean, Russian, Czech, Turkish.
- The script never modifies the original PDF; output is always a new file (`_highlights.pdf` suffix by default).

## Planned features

- GUI (tkinter or web-based) for drag-and-drop workflow
- Packaging as standalone executable (PyInstaller)
- Support for Speechify's newer export formats if they change the HTML structure
