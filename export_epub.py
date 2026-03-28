"""
BookConvert - EPUB Exporter
Creates a proper EPUB3 file with linear structure and standard navigation.
Three sections: Short Version, Groups, Chunks.
"""

import re
import tempfile
from pathlib import Path
from typing import Optional

import ebooklib
from ebooklib import epub
import markdown

CHUNK_BREAK_HTML = '<div class="chunk-break" aria-hidden="true"><span>⁂</span></div>'


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from a markdown block."""
    return re.sub(r"^---\s*[\s\S]*?---\s*", "", text or "", flags=re.DOTALL).strip()


def _preprocess_markdown(text: str) -> str:
    """Preprocess markdown to ensure lists are properly recognized."""
    lines = text.split("\n")
    result_lines = []

    for i, line in enumerate(lines):
        # Check if current line is a list item
        is_list_item = re.match(r"^[\s]*[-*+]\s", line) or re.match(
            r"^[\s]*\d+\.\s", line
        )

        if is_list_item:
            # Check if previous line is not empty and not a list item
            if i > 0:
                prev_line = lines[i - 1].strip()
                prev_is_list = re.match(r"^[-*+]\s", prev_line) or re.match(
                    r"^\d+\.\s", prev_line
                )

                # Add blank line before list if needed
                if prev_line and not prev_is_list:
                    result_lines.append("")

        result_lines.append(line)

    return "\n".join(result_lines)


def _md_to_html(md_text: str) -> str:
    """Convert markdown to HTML for EPUB content."""
    if not md_text or not md_text.strip():
        return "<p><em>No content available.</em></p>"

    # Remove YAML frontmatter
    text = _strip_frontmatter(md_text)

    # Remove wrapping code fences if present
    backticks = chr(96) * 3
    if re.match(rf"^{backticks}[\w]*\s*\n", text) and re.search(
        rf"\n{backticks}\s*$", text
    ):
        text = re.sub(rf"^{backticks}[\w]*\s*\n", "", text)
        text = re.sub(rf"\n{backticks}\s*$", "", text)

    # Preprocess markdown to fix list formatting
    text = _preprocess_markdown(text)

    # Convert markdown to HTML
    try:
        html = markdown.markdown(
            text,
            extensions=[
                "tables",
                "fenced_code",
                "codehilite",
                "toc",
                "sane_lists",
                "nl2br",
                "smarty",
                "attr_list",
                "def_list",
                "abbr",
                "md_in_html",
            ],
            output_format="html",
        )
        return html
    except Exception as e:
        # Fallback: escape and wrap in pre
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{escaped}</pre>"


def _build_chunk_display(chunks: list[dict]) -> str:
    """Join chunk bodies with a neutral visual separator."""
    parts = [c["body"] for c in chunks if c.get("body", "").strip()]
    return f"\n\n{CHUNK_BREAK_HTML}\n\n".join(parts)


def _create_chapter(
    title: str,
    content_html: str,
    file_name: str,
    book: epub.EpubBook,
) -> epub.EpubHtml:
    """Create an EPUB chapter with styled content."""

    chapter = epub.EpubHtml(title=title, file_name=file_name, lang="en")

    # Add CSS styling for EPUB readers
    chapter.content = f"""<style>
        body {{
            font-family: Georgia, 'Times New Roman', serif;
            line-height: 1.6;
            margin: 1em;
            padding: 0;
        }}
        h1 {{
            font-size: 1.8em;
            margin: 1em 0 0.5em;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 0.3em;
        }}
        h2 {{
            font-size: 1.4em;
            margin: 1.2em 0 0.4em;
            color: #34495e;
        }}
        h3 {{
            font-size: 1.2em;
            margin: 1em 0 0.3em;
            color: #7f8c8d;
        }}
        p {{
            margin: 0.8em 0;
            text-align: justify;
        }}
        strong {{
            color: #e67e22;
        }}
        code {{
            background: #f4f4f4;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        pre {{
            background: #f8f8f8;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 1em;
            overflow-x: auto;
            margin: 1em 0;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        ul, ol {{
            margin: 0.5em 0 1em 1.5em;
        }}
        li {{
            margin-bottom: 0.3em;
        }}
        hr {{
            border: none;
            border-top: 1px solid #ddd;
            margin: 1.5em 0;
        }}
        blockquote {{
            border-left: 3px solid #3498db;
            padding-left: 1em;
            color: #7f8c8d;
            margin: 1em 0;
            font-style: italic;
        }}
        .chunk-break {{
            display: flex;
            align-items: center;
            gap: 0.75em;
            margin: 1.75em 0;
            color: #7f8c8d;
            break-before: page;
            page-break-before: always;
        }}
        .chunk-break::before,
        .chunk-break::after {{
            content: "";
            flex: 1;
            border-top: 1px solid #ddd;
        }}
        .chunk-break span {{
            padding: 0 0.5em;
            letter-spacing: 0.2em;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1em 0;
        }}
        th {{
            background: #f4f4f4;
            color: #2c3e50;
            font-weight: bold;
            text-align: left;
            padding: 0.6em;
            border: 1px solid #ddd;
        }}
        td {{
            padding: 0.5em;
            border: 1px solid #ddd;
            vertical-align: top;
        }}
        tr:nth-child(even) {{
            background: #f9f9f9;
        }}
        .section-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2em;
            margin: -1em -1em 1em -1em;
            text-align: center;
        }}
        .section-header h1 {{
            color: white;
            border: none;
            margin: 0;
            font-size: 2.2em;
        }}
        .section-header p {{
            color: rgba(255,255,255,0.9);
            margin: 0.5em 0 0;
            text-align: center;
        }}
    </style>
    {content_html}"""

    book.add_item(chapter)
    return chapter


def export_epub(
    book_dir: Path,
    book_name: str,
    generate_final: bool = True,
) -> Path:
    """Export distillation results to EPUB with linear structure."""

    print(f"   📚 Creating EPUB for: {book_name}")

    # Find files
    final_path = book_dir / "final.md" if generate_final else None
    synthesis_dir = book_dir / "synthesis"
    distilled_dir = book_dir / "distilled"
    combined_path = synthesis_dir / "combined.md" if synthesis_dir.exists() else None
    distilled_files = (
        sorted(distilled_dir.glob("*_distilled.md")) if distilled_dir.exists() else []
    )

    # Read raw files
    final_raw = (
        final_path.read_text(encoding="utf-8")
        if final_path and final_path.exists()
        else ""
    )

    combined_raw = (
        combined_path.read_text(encoding="utf-8")
        if combined_path and combined_path.exists()
        else ""
    )

    chunks = []
    for df in sorted(distilled_files):
        if df.exists():
            chunk_num = re.search(r"^(\d+)_", df.name)
            num = chunk_num.group(1) if chunk_num else "?"
            raw = df.read_text(encoding="utf-8")
            chunks.append(
                {
                    "num": num,
                    "raw": raw,
                    "body": _strip_frontmatter(raw),
                }
            )

    combined_display = _build_chunk_display(chunks) if chunks else combined_raw
    if not combined_display.strip():
        combined_display = combined_raw

    # Create EPUB book
    book = epub.EpubBook()
    book.set_identifier(f"bookconvert-{book_name.lower().replace(' ', '-')}")
    book.set_title(book_name)
    book.set_language("en")
    book.add_author("BookConvert")

    # Add metadata
    book.add_metadata("DC", "description", f"Intellectual Distillation of {book_name}")
    book.add_metadata("DC", "publisher", "BookConvert")

    # Create chapters
    chapters = []

    # ── Section 1: Short Version ──────────────────────────
    if final_raw.strip():
        section1_html = f"""
        <div class="section-header">
            <h1>Short Version</h1>
            <p>The distilled essence of {book_name}</p>
        </div>
        {_md_to_html(final_raw)}
        """

        chapter1 = _create_chapter(
            title="1. Short Version",
            content_html=section1_html,
            file_name="section1_short.xhtml",
            book=book,
        )
        chapters.append(chapter1)

    # ── Section 2: Combined Knowledge ──────────────────────
    if combined_display.strip():
        section2_html = f"""
        <div class="section-header">
            <h1>Combined Knowledge</h1>
            <p>All distilled insights from {book_name}</p>
        </div>
        {_md_to_html(combined_display)}
        """

        chapter2 = _create_chapter(
            title="2. Combined Knowledge",
            content_html=section2_html,
            file_name="section2_combined.xhtml",
            book=book,
        )
        chapters.append(chapter2)

    # ── Section 3: All Chunks ─────────────────────────────
    if chunks:
        # Create section header
        chunks_html = f"""
        <div class="section-header">
            <h1>All Chunks</h1>
            <p>Individual distilled chunks</p>
        </div>
        """

        # Add each chunk as subsection
        for i, c in enumerate(chunks):
            chunks_html += f"""
            <h2>Chunk {c["num"]}</h2>
            {_md_to_html(c["body"])}
            """

        chapter3 = _create_chapter(
            title="3. All Chunks",
            content_html=chunks_html,
            file_name="section3_chunks.xhtml",
            book=book,
        )
        chapters.append(chapter3)

    # If no content, create a placeholder
    if not chapters:
        placeholder_html = f"""
        <div class="section-header">
            <h1>{book_name}</h1>
            <p>No distillation content available yet.</p>
        </div>
        <p>Please run the distillation process first.</p>
        """

        placeholder = _create_chapter(
            title=book_name,
            content_html=placeholder_html,
            file_name="placeholder.xhtml",
            book=book,
        )
        chapters.append(placeholder)

    # Add chapters to book
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define CSS style
    style = """
    body { font-family: Georgia, serif; }
    """
    nav_css = epub.EpubItem(
        uid="style", file_name="style/default.css", media_type="text/css", content=style
    )
    book.add_item(nav_css)

    # Create spine
    book.spine = ["nav"] + chapters

    # Write EPUB file
    epub_filename = f"{book_name}.epub"
    epub_path = book_dir / epub_filename

    try:
        epub.write_epub(str(epub_path), book, {})
        file_size = epub_path.stat().st_size
        print(f"   📚 Exported → {epub_filename} ({file_size:,} bytes)")
        return epub_path
    except Exception as e:
        print(f"   ❌ EPUB export failed: {e}")
        raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python export_epub.py <book_dir> <book_name>")
        sys.exit(1)

    book_dir = Path(sys.argv[1])
    book_name = sys.argv[2]

    try:
        export_epub(book_dir, book_name)
        print("✅ EPUB export completed successfully!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
