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

1. **HTML parsing** (`extract_highlights`) — splits saved Speechify HTML by page-label buttons (language-aware via `_PAGE_WORDS`), then extracts highlight blocks via regex on `aria-label` and CSS color class attributes. Prefers the `aria-label` text when it is longer than the visible span (it can carry the full text).

2. **Start-position search — Pass 1** (`find_start`) — for each highlight, searches the PDF page (±2 page tolerance) using progressively shorter word prefixes (longest match first, down to 3 words) to handle hyphenation and orphaned line-starters.

3. **Rect expansion — Pass 2** — for complete highlights: `find_end_on_page` locates the end suffix across up to `_MAX_SPAN_PAGES` (8) pages; `annotate_span` collects line rects via `_collect_lines` and annotates each spanned page. For truncated highlights (~80-char Speechify cutoff): `place_truncated` caps the annotation at the next highlight's y-position or 8 line-heights, whichever is smaller.

4. **Annotation write** (`_safe_highlight`) — validates rects with `_valid_rects` (drops zero-area or out-of-bounds rects), calls PyMuPDF `add_highlight_annot`, sets color from `COLOR_MAP`, attaches note as annotation content.

## Key constraints

- Speechify's sidebar only exposes the first ~80 characters of long highlights — truncated highlights are detected via trailing `"..."` and handled differently.
- The HTML page-section splitter must match the UI language; `_PAGE_WORDS` covers English, German, Spanish, Italian, French, Japanese, Korean, Russian, Czech, Turkish.
- The script never modifies the original PDF; output is always a new file (`_highlights.pdf` suffix by default).

## Planned features

- GUI (tkinter or web-based) for drag-and-drop workflow
- Packaging as standalone executable (PyInstaller)
- Support for Speechify's newer export formats if they change the HTML structure
