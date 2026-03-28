"""
BookConvert - HTML Exporter
Takes template.html, replaces placeholders with raw content.
Zero escaping. Zero processing. Just replace and write.
"""

import html as html_mod
import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "template.html"
CHUNK_BREAK_HTML = '<div class="chunk-break" aria-hidden="true"><span>⁂</span></div>'


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from a markdown block."""
    return re.sub(r"^---\s*[\s\S]*?---\s*", "", text or "", flags=re.DOTALL).strip()


def _chunk_body(raw: str) -> str:
    """Return the rendered body for a distilled chunk."""
    return _strip_frontmatter(raw)


def _build_chunk_display(chunks: list[dict]) -> str:
    """Join chunk bodies with a neutral visual separator."""
    parts = [body for body in (_chunk_body(c["raw"]) for c in chunks) if body]
    return f"\n\n{CHUNK_BREAK_HTML}\n\n".join(parts)


def export_html(
    book_dir: Path,
    book_name: str,
    generate_final: bool = True,
) -> Path:
    """Export distillation results to HTML using template replacement."""

    # Load template
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Find files
    final_path = book_dir / "final.md" if generate_final else None
    synthesis_dir = book_dir / "synthesis"
    distilled_dir = book_dir / "distilled"
    combined_path = synthesis_dir / "combined.md" if synthesis_dir.exists() else None
    distilled_files = (
        sorted(distilled_dir.glob("*_distilled.md")) if distilled_dir.exists() else []
    )

    # ── Read raw files ──────────────────────────────────────
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
            chunks.append({"num": num, "raw": raw})

    combined_display = _build_chunk_display(chunks) if chunks else combined_raw
    if not combined_display.strip():
        combined_display = combined_raw

    # ── Build accordion HTML ────────────────────────────────
    chunks_accordion = ""
    for i, c in enumerate(chunks):
        chunks_accordion += (
            f'<details class="chunk-accordion" data-source="data-chunk-{i}" data-target="chunk-{i}">\n'
            f"    <summary>📄 Chunk {c['num']}</summary>\n"
            f'    <div class="content" id="chunk-{i}"><p class="loading">Rendering...</p></div>\n'
            f"</details>\n"
        )
    if not chunks:
        chunks_accordion = '<p class="empty">No distilled chunks available yet.</p>'

    # ── Build textarea HTML (raw content, zero processing) ──
    data_textareas = ""
    for i, c in enumerate(chunks):
        data_textareas += (
            f'<textarea id="data-chunk-{i}" hidden>{c["raw"]}</textarea>\n'
        )

    # ── Replace placeholders ────────────────────────────────
    result = template
    result = result.replace("{{BOOK_NAME}}", html_mod.escape(book_name))
    result = result.replace("{{FINAL_TEXT}}", final_raw)
    result = result.replace("{{COMBINED_TEXT}}", combined_display)
    result = result.replace("{{CHUNKS_ACCORDION}}", chunks_accordion)
    result = result.replace("{{DATA_TEXTAREAS}}", data_textareas)

    # Write
    html_filename = f"{book_name}.html"
    html_path = book_dir / html_filename
    html_path.write_text(result, encoding="utf-8")
    print(f"   🌐 Exported → {html_filename} ({len(result):,} bytes)")
    return html_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python export_html.py <book_dir> <book_name>")
        sys.exit(1)

    book_dir = Path(sys.argv[1])
    book_name = sys.argv[2]
    export_html(book_dir, book_name)
