"""
BookConvert - HTML Exporter
Takes template.html, replaces placeholders with raw content.
Zero escaping. Zero processing. Just replace and write.
"""

import html as html_mod
import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "template.html"


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
    group_files = (
        sorted(synthesis_dir.glob("group_*.md")) if synthesis_dir.exists() else []
    )
    distilled_files = (
        sorted(distilled_dir.glob("*_distilled.md")) if distilled_dir.exists() else []
    )

    # ── Read raw files ──────────────────────────────────────
    final_raw = (
        final_path.read_text(encoding="utf-8")
        if final_path and final_path.exists()
        else ""
    )

    groups = []
    for gf in group_files:
        if gf.exists():
            group_num = re.search(r"group_(\d+)", gf.name)
            num = group_num.group(1) if group_num else "?"
            groups.append(
                {
                    "num": num,
                    "name": f"Group {num}",
                    "raw": gf.read_text(encoding="utf-8"),
                }
            )

    chunks = []
    for df in sorted(distilled_files):
        if df.exists():
            chunk_num = re.search(r"^(\d+)_", df.name)
            num = chunk_num.group(1) if chunk_num else "?"
            raw = df.read_text(encoding="utf-8")
            title_match = re.search(r"title:\s*(.+)", raw)
            title = title_match.group(1).strip() if title_match else df.stem
            chunks.append({"num": num, "title": title, "raw": raw})

    # ── Build accordion HTML ────────────────────────────────
    groups_accordion = ""
    for i, g in enumerate(groups):
        groups_accordion += (
            f'<details class="chunk-accordion" data-source="data-group-{i}" data-target="group-{i}">\n'
            f"    <summary>📂 {html_mod.escape(g['name'])}</summary>\n"
            f'    <div class="content" id="group-{i}"><p class="loading">Rendering...</p></div>\n'
            f"</details>\n"
        )
    if not groups:
        groups_accordion = '<p class="empty">No group distillations available yet.</p>'

    chunks_accordion = ""
    for i, c in enumerate(chunks):
        chunks_accordion += (
            f'<details class="chunk-accordion" data-source="data-chunk-{i}" data-target="chunk-{i}">\n'
            f"    <summary>📄 Chunk {c['num']}: {html_mod.escape(c['title'][:80])}</summary>\n"
            f'    <div class="content" id="chunk-{i}"><p class="loading">Rendering...</p></div>\n'
            f"</details>\n"
        )
    if not chunks:
        chunks_accordion = '<p class="empty">No distilled chunks available yet.</p>'

    # ── Build textarea HTML (raw content, zero processing) ──
    data_textareas = ""
    for i, g in enumerate(groups):
        data_textareas += (
            f'<textarea id="data-group-{i}" hidden>{g["raw"]}</textarea>\n'
        )
    for i, c in enumerate(chunks):
        data_textareas += (
            f'<textarea id="data-chunk-{i}" hidden>{c["raw"]}</textarea>\n'
        )

    # ── Replace placeholders ────────────────────────────────
    result = template
    result = result.replace("{{BOOK_NAME}}", html_mod.escape(book_name))
    result = result.replace("{{FINAL_TEXT}}", final_raw)
    result = result.replace("{{GROUPS_ACCORDION}}", groups_accordion)
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
