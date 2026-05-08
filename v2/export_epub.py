# FILE: v2/export_epub.py
# PURPOSE: Render a V2 book.yaml into a progressive-disclosure EPUB3 artifact.
# OWNS: V2 YAML-to-EPUB conversion, chapter assembly with <details> expandables.
# NOTE: Hardcoded to EPUB 3 (2011!) — <details> is spec-legal there. No more EPUB 2 stone-age.
# EXPORTS: export_epub, main.
# DOCS: README.md, v2/process.py, v2/schema.py

"""
Rixie V2 — EPUB Exporter

Reads a workspace/book.yaml, converts markdown summaries to HTML,
and produces an EPUB3 file with two-pass progressive disclosure:

  Part 1 — Short Summaries (read-through):
    Title page → Abstract → Chapter 1 Short → Chapter 2 Short → ...
    Each short summary ends with a [📖 Read full summary →] link.

  Part 2 — Detailed Summaries (reference):
    Chapter 1 Long → Chapter 2 Long → ...
    Each long summary starts with a [← Back to short] link.

  Readers can also jump between sections via the Table of Contents
  (Short Summaries section / Detailed Summaries section).
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any

import markdown
import yaml
from ebooklib import epub

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _md_to_html(md_text: str) -> str:
    """Convert markdown text to HTML."""
    if not md_text or not md_text.strip():
        return "<p><em>No content available.</em></p>"

    # Strip any YAML frontmatter
    text = re.sub(r"^---\s*[\s\S]*?---\s*", "", md_text or "", flags=re.DOTALL).strip()

    # Strip top-level fenced code blocks (LLMs sometimes wrap output)
    backticks = chr(96) * 3
    if re.match(rf"^{backticks}[\w]*\s*\n", text) and re.search(rf"\n{backticks}\s*$", text):
        text = re.sub(rf"^{backticks}[\w]*\s*\n", "", text)
        text = re.sub(rf"\n{backticks}\s*$", "", text)

    try:
        return markdown.markdown(
            text,
            extensions=[
                "tables", "fenced_code", "codehilite",
                "sane_lists", "nl2br", "smarty",
                "attr_list", "def_list", "abbr", "md_in_html",
            ],
            output_format="html",
        )
    except Exception:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{escaped}</pre>"


EPUB_CSS = textwrap.dedent("""\
    /* ── Typography ── */
    body {
        font-family: Georgia, 'Times New Roman', serif;
        line-height: 1.7;
        margin: 1em;
        padding: 0;
        color: #1a1a2e;
    }
    h1 {
        font-size: 1.8em;
        margin: 1em 0 0.5em;
        color: #2c3e50;
        border-bottom: 2px solid #d04030;
        padding-bottom: 0.3em;
    }
    h2 {
        font-size: 1.4em;
        margin: 1.2em 0 0.4em;
        color: #34495e;
    }
    h3 {
        font-size: 1.2em;
        margin: 1em 0 0.3em;
        color: #5a637a;
    }
    p {
        margin: 0.8em 0;
        text-align: justify;
    }
    strong { color: #d04030; }
    em { color: #5048b0; }
    code {
        background: #f4f4f4;
        padding: 0.2em 0.4em;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 0.9em;
    }
    pre {
        background: #f8f8f8;
        border: 1px solid #ddd;
        border-radius: 4px;
        padding: 1em;
        overflow-x: auto;
        margin: 1em 0;
    }
    pre code { background: none; padding: 0; }
    ul, ol { margin: 0.5em 0 1em 1.5em; }
    li { margin-bottom: 0.3em; }
    hr {
        border: none;
        border-top: 1px solid #ddd;
        margin: 1.5em 0;
    }
    blockquote {
        border-left: 3px solid #d04030;
        padding-left: 1em;
        color: #555568;
        margin: 1em 0;
        font-style: italic;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 1em 0;
    }
    th {
        background: #f4f4f4;
        color: #2c3e50;
        font-weight: bold;
        text-align: left;
        padding: 0.6em;
        border: 1px solid #ddd;
    }
    td {
        padding: 0.5em;
        border: 1px solid #ddd;
        vertical-align: top;
    }
    tr:nth-child(even) { background: #f9f9f9; }

    /* ── Section styling ── */
    .section-header {
        background: linear-gradient(135deg, #d04030 0%, #5048b0 100%);
        color: white;
        padding: 2em;
        margin: -1em -1em 1em -1em;
        text-align: center;
    }
    .section-header h1 {
        color: white;
        border: none;
        margin: 0;
        font-size: 2.2em;
    }
    .section-header p {
        color: rgba(255,255,255,0.9);
        margin: 0.5em 0 0;
        text-align: center;
        font-style: italic;
    }

    /* ── Cross-links (Short ↔ Long) ── */
    .nav-links {
        margin: 1.5em 0;
        padding: 0.75em;
        text-align: center;
    }
    .forward-link, .back-link {
        display: inline-block;
        padding: 0.5em 1.25em;
        background: #5048b0;
        color: #ffffff !important;
        text-decoration: none;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.95em;
    }
    .forward-link:hover, .back-link:hover {
        background: #d04030;
    }
    .section-divider {
        text-align: center;
        margin: 2em 0;
        padding: 1.5em;
        color: #9999aa;
        font-style: italic;
        border-top: 1px solid #ddd;
        border-bottom: 1px solid #ddd;
    }

    /* ── Chapter navigation ── */
    .chapter-start {
        page-break-before: always;
        break-before: page;
    }
    .chapter-label {
        font-size: 0.75em;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: #9999aa;
        margin-bottom: 0.5em;
    }
    /* ── Abstract ── */
    .abstract-box {
        background: #f0ede6;
        border-left: 4px solid #5048b0;
        padding: 1.25em 1.5em;
        margin: 1.5em 0;
        border-radius: 0 8px 8px 0;
    }
    .abstract-box p:first-child { margin-top: 0; }
    .abstract-box p:last-child { margin-bottom: 0; }

    /* ── Title page ── */
    .title-page {
        text-align: center;
        padding: 3em 1em;
        page-break-after: always;
        break-after: page;
    }
    .title-page h1 {
        font-size: 2.5em;
        border: none;
        margin-bottom: 0.5em;
    }
    .title-page .author {
        font-size: 1.1em;
        color: #555568;
        margin-bottom: 2em;
    }
    .title-page .meta {
        font-size: 0.8em;
        color: #9999aa;
        letter-spacing: 0.06em;
    }
    .title-page .generator {
        font-size: 0.75em;
        color: #aaaaaa;
        margin-top: 3em;
        font-style: italic;
    }

    /* ── End page ── */
    .end-page {
        text-align: center;
        padding: 4em 1em;
        page-break-before: always;
        break-before: page;
    }
    .end-page .closing {
        font-size: 1.3em;
        color: #2c3e50;
        margin-bottom: 1em;
        font-style: italic;
    }
    .end-page .attribution {
        font-size: 0.85em;
        color: #9999aa;
        letter-spacing: 0.06em;
    }
""")


def _create_epub_chapter(
    title: str,
    content_html: str,
    file_name: str,
    book: epub.EpubBook,
    *,
    chapter_start: bool = False,
) -> epub.EpubHtml:
    """Create a single EPUB chapter with embedded CSS."""
    extra_class = ' class="chapter-start"' if chapter_start else ""
    chapter = epub.EpubHtml(title=title, file_name=file_name, lang="en")
    chapter.content = f"""<style>{EPUB_CSS}</style>
    <div{extra_class}>
    {content_html}
    </div>"""
    book.add_item(chapter)
    return chapter


def _build_title_page(book_name: str, authors: list[str]) -> str:
    """Build the title page HTML."""
    author_str = ", ".join(authors) if authors else "Rixie Edition"
    return f"""
    <div class="title-page">
        <h1>{book_name}</h1>
        <div class="author">by {author_str}</div>
        <div class="meta">Interactive Edition &bull; V2</div>
        <div class="generator">Generated by Rixie V2 &mdash; Knowledge Distillation Engine</div>
    </div>"""


def _build_abstract_section(abstract: str) -> str:
    """Build the abstract/introduction section."""
    abstract_html = _md_to_html(abstract)
    return f"""
    <div class="section-header"><h1>Abstract</h1><p>The distilled essence</p></div>
    <div class="abstract-box">{abstract_html}</div>"""


def _build_short_chapter_section(chapter: dict[str, Any], index: int) -> str:
    """Build a short summary chapter page with a forward link to the long version."""
    ch_title = chapter.get("title") or f"Chapter {index}"
    short = chapter.get("short_summary") or ""
    short_html = _md_to_html(short)

    return f"""
    <div class="chapter-label">Chapter {index}</div>
    <h2>{ch_title}</h2>
    {short_html}
    <div class="nav-links">
        <a href="long_{index:03d}.xhtml" class="forward-link">📖 Read full summary →</a>
    </div>"""


def _build_long_chapter_section(chapter: dict[str, Any], index: int) -> str:
    """Build a detailed summary chapter page with a back link to the short version."""
    ch_title = chapter.get("title") or f"Chapter {index}"
    detailed = chapter.get("detailed_summary") or ""
    detailed_html = _md_to_html(detailed)

    return f"""
    <div class="chapter-label">Chapter {index} — Detailed Summary</div>
    <h2>{ch_title}</h2>
    <div class="nav-links">
        <a href="short_{index:03d}.xhtml" class="back-link">← Back to short summary</a>
    </div>
    {detailed_html}"""


def _build_end_page(book_name: str, chapter_count: int) -> str:
    """Build the closing end page."""
    return f"""
    <div class="end-page">
        <div class="closing">Fin</div>
        <div class="attribution">
            <em>{book_name}</em> &mdash; {chapter_count} chapters distilled<br/>
            Rixie V2 Knowledge Distillation
        </div>
    </div>"""


def export_epub(workspace_dir: Path) -> Path:
    """Export a V2 book.yaml workspace as an EPUB3 file with two-pass navigation.

    Structure:
      Part 1 — Short Summaries (title → abstract → short ch1 → short ch2 → ...)
      Part 2 — Detailed Summaries (long ch1 → long ch2 → ... → end)
      Each short → long and long → short via hyperlinks + TOC sections.

    Returns the path to the generated .epub file.
    """
    book_yaml = workspace_dir / "book.yaml"

    if not book_yaml.exists():
        raise FileNotFoundError(f"book.yaml not found in {workspace_dir}")

    data = yaml.safe_load(book_yaml.read_text(encoding="utf-8")) or {}
    meta = data.get("metadata", {})
    book_name = meta.get("title") or workspace_dir.name
    authors = meta.get("authors") or []
    slug = meta.get("slug") or workspace_dir.name

    overview = data.get("overview", {}) or {}
    abstract = overview.get("ultra_dense_summary") or ""
    chapters_raw = data.get("chapters") or []
    chapters = sorted(chapters_raw, key=lambda c: c.get("order", 0))

    print(f"   📚 Creating EPUB for: {book_name}")
    print(f"      Slug: {slug}")
    print(f"      Authors: {', '.join(authors) if authors else 'Unknown'}")
    print(f"      Chapters: {len(chapters)}")
    print(f"      Abstract: {'✓' if abstract.strip() else '✗ missing'}")
    print(f"      Mode: Short summaries → linked to detailed summaries")

    # ── Build EPUB (V3) ──
    book = epub.EpubBook()
    book.EPUB_VERSION = 3
    book.set_identifier(f"rixie-v2-{slug}")
    book.set_title(book_name)
    book.set_language(meta.get("language") or "en")
    book.add_author(", ".join(authors) if authors else "Rixie V2")
    book.add_metadata("DC", "description", f"Knowledge distillation of {book_name}")
    book.add_metadata("DC", "publisher", "Rixie V2")
    book.add_metadata("DC", "date", meta.get("created_at", ""))

    all_spine: list[epub.EpubHtml] = []

    # ── 1. Title page ──
    title_chapter = _create_epub_chapter(
        title=f"Title — {book_name}",
        content_html=_build_title_page(book_name, authors),
        file_name="title.xhtml",
        book=book,
    )
    all_spine.append(title_chapter)

    # ── 2. Abstract (if present) ──
    if abstract.strip():
        abstract_chapter = _create_epub_chapter(
            title="Abstract",
            content_html=_build_abstract_section(abstract),
            file_name="abstract.xhtml",
            book=book,
            chapter_start=True,
        )
        all_spine.append(abstract_chapter)

    # ── 3. Short summary chapters (Part 1) ──
    short_chapters: list[epub.EpubHtml] = []
    for i, ch in enumerate(chapters, start=1):
        ch_title = ch.get("title") or f"Chapter {i}"
        short_ch = _create_epub_chapter(
            title=ch_title,
            content_html=_build_short_chapter_section(ch, i),
            file_name=f"short_{i:03d}.xhtml",
            book=book,
            chapter_start=False,
        )
        short_chapters.append(short_ch)

    all_spine.extend(short_chapters)

    # ── 4. Section divider between shorts and longs ──
    part_header = _create_epub_chapter(
        title="Detailed Summaries",
        content_html="""
    <div class="section-header">
        <h1>Detailed Summaries</h1>
        <p>In-depth breakdowns for each chapter</p>
    </div>""",
        file_name="part2.xhtml",
        book=book,
        chapter_start=True,
    )
    all_spine.append(part_header)

    # ── 5. Long / detailed summary chapters (Part 2) ──
    long_chapters: list[epub.EpubHtml] = []
    for i, ch in enumerate(chapters, start=1):
        ch_title = f"{ch.get('title') or f'Chapter {i}'} — Detailed"
        long_ch = _create_epub_chapter(
            title=ch_title,
            content_html=_build_long_chapter_section(ch, i),
            file_name=f"long_{i:03d}.xhtml",
            book=book,
            chapter_start=True,
        )
        long_chapters.append(long_ch)

    all_spine.extend(long_chapters)

    # ── 6. End page ──
    end_chapter = _create_epub_chapter(
        title=f"End — {book_name}",
        content_html=_build_end_page(book_name, len(chapters)),
        file_name="end.xhtml",
        book=book,
        chapter_start=True,
    )
    all_spine.append(end_chapter)

    # ── Navigation (hierarchical TOC) ──
    book.toc = [
        title_chapter,
        abstract_chapter if abstract.strip() else None,
        (epub.Section("Short Summaries"), short_chapters),
        (epub.Section("Detailed Summaries"), long_chapters),
        end_chapter,
    ]
    # Filter out None entries (when abstract is missing)
    book.toc = [item for item in book.toc if item is not None]

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # ── Stylesheet ──
    style = epub.EpubItem(
        uid="style_default",
        file_name="style/default.css",
        media_type="text/css",
        content=EPUB_CSS,
    )
    book.add_item(style)
    book.spine = ["nav"] + all_spine

    # ── Write ──
    epub_filename = f"{slug}.epub"
    epub_path = workspace_dir / epub_filename
    epub.write_epub(str(epub_path), book, {})

    file_size = epub_path.stat().st_size
    print(f"   📚 Exported → {epub_filename} ({file_size:,} bytes)")
    return epub_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry: python -m v2.export_epub <workspace_dir>"""
    argv = list(argv or [])
    if not argv:
        import sys
        argv = sys.argv[1:]

    if len(argv) < 1:
        print("Usage: python -m v2.export_epub <workspace_dir>")
        print("Example: python -m v2.export_epub output/v2/my-book")
        return 1

    workspace_dir = Path(argv[0]).resolve()
    if not workspace_dir.is_dir():
        print(f"❌ Not a directory: {workspace_dir}")
        return 1

    try:
        epub_path = export_epub(workspace_dir)
        print(f"✅ EPUB exported: {epub_path}")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
