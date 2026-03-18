"""
BookConvert - HTML Exporter
Exports distillation results to a beautiful self-contained HTML file.

Uses marked.js from CDN for client-side markdown rendering.
Python just embeds raw markdown — the browser does all the work.
"""

import html as html_mod
import re
from pathlib import Path


def escape_for_js(text: str) -> str:
    """Escape text for embedding inside a JS template literal."""
    text = text.replace("\\", "\\\\")
    text = text.replace("`", "\\`")
    text = text.replace("${", "\\${")
    return text


def generate_html(
    book_name: str,
    final_path: Path | None,
    group_files: list[Path],
) -> str:
    """Generate HTML that renders markdown client-side via marked.js."""

    # Load raw markdown for final synthesis
    final_md = ""
    if final_path and final_path.exists():
        final_md = final_path.read_text(encoding="utf-8")

    # Load raw markdown for groups
    groups = []
    for gf in group_files:
        if gf.exists():
            group_num = re.search(r"group_(\d+)", gf.name)
            num = group_num.group(1) if group_num else "?"
            groups.append(
                {
                    "num": num,
                    "name": f"Group {num}",
                    "md": gf.read_text(encoding="utf-8"),
                }
            )

    # Build group HTML slots
    groups_html = ""
    for i, g in enumerate(groups):
        groups_html += f"""
    <details class="group-accordion" data-group="{i}">
        <summary>📂 {g["name"]}</summary>
        <div class="group-content" id="group-{i}"><p class="loading">Rendering...</p></div>
    </details>"""

    if not groups:
        groups_html = '<p class="empty">No group distillations available yet.</p>'

    # Embed raw markdown as JSON-safe strings
    final_md_escaped = escape_for_js(final_md)
    groups_js_array = ",\n        ".join(
        f'{{"name": "{g["name"]}", "md": `{escape_for_js(g["md"])}`}}' for g in groups
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(book_name)} — Distillation</title>

<!-- marked.js: Markdown → HTML (43KB gzipped, handles everything) -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

<style>
    :root {{
        --bg: #0d1117;
        --surface: #161b22;
        --surface-hover: #1c2128;
        --border: #30363d;
        --text: #e6edf3;
        --text-dim: #8b949e;
        --accent: #58a6ff;
        --green: #3fb950;
        --orange: #d29922;
        --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
        --mono: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, monospace;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
        font-family: var(--font);
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        padding: 2rem;
        max-width: 900px;
        margin: 0 auto;
    }}

    /* Markdown content styling */
    .content h1 {{ font-size: 1.8rem; margin: 1rem 0 0.5rem; color: var(--accent); }}
    .content h2 {{ font-size: 1.3rem; margin: 1.5rem 0 0.5rem; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }}
    .content h3 {{ font-size: 1.1rem; margin: 1.2rem 0 0.4rem; color: var(--green); }}
    .content p {{ margin-bottom: 0.8rem; }}
    .content strong {{ color: var(--orange); }}
    .content code {{ background: var(--surface); padding: 0.15em 0.4em; border-radius: 4px; font-family: var(--mono); font-size: 0.9em; color: var(--green); }}
    .content pre {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 1rem; overflow-x: auto; margin: 1rem 0; }}
    .content pre code {{ background: none; padding: 0; color: var(--text); }}
    .content ul, .content ol {{ margin: 0.5rem 0 1rem 1.5rem; }}
    .content li {{ margin-bottom: 0.4rem; }}
    .content hr {{ border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }}
    .content blockquote {{ border-left: 3px solid var(--accent); padding-left: 1rem; color: var(--text-dim); margin: 1rem 0; }}

    /* Tables */
    .content table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
    .content th {{ background: var(--surface); color: var(--accent); font-weight: 600; text-align: left; padding: 0.6rem 0.8rem; border: 1px solid var(--border); }}
    .content td {{ padding: 0.5rem 0.8rem; border: 1px solid var(--border); vertical-align: top; }}
    .content tr:nth-child(even) {{ background: var(--surface); }}
    .content tr:hover {{ background: var(--surface-hover); }}

    .empty {{ color: var(--text-dim); font-style: italic; }}
    .loading {{ color: var(--text-dim); font-style: italic; }}

    /* Header */
    .header {{ margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 2px solid var(--border); }}
    .header h1 {{ font-size: 2rem; color: var(--accent); border: none; margin: 0; }}
    .subtitle {{ color: var(--text-dim); font-size: 0.9rem; }}

    /* Tabs */
    .tabs {{ display: flex; gap: 0; margin-bottom: 0; border-bottom: 2px solid var(--border); }}
    .tab-btn {{
        background: var(--surface); border: 1px solid var(--border); border-bottom: none;
        color: var(--text-dim); padding: 0.75rem 1.5rem; cursor: pointer;
        font-size: 0.95rem; font-family: var(--font); transition: all 0.2s;
        border-radius: 8px 8px 0 0; margin-right: -1px;
    }}
    .tab-btn:hover {{ background: var(--surface-hover); color: var(--text); }}
    .tab-btn.active {{
        background: var(--bg); color: var(--accent);
        border-bottom: 2px solid var(--bg); margin-bottom: -2px; font-weight: 600;
    }}
    .tab-content {{
        display: none; padding: 1.5rem; background: var(--bg);
        border: 1px solid var(--border); border-top: none; border-radius: 0 0 8px 8px;
    }}
    .tab-content.active {{ display: block; }}

    /* Accordions */
    .group-accordion {{ margin-bottom: 0.5rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
    .group-accordion summary {{
        background: var(--surface); padding: 1rem 1.25rem; cursor: pointer;
        font-weight: 600; color: var(--accent); transition: background 0.2s; user-select: none;
    }}
    .group-accordion summary:hover {{ background: var(--surface-hover); }}
    .group-accordion[open] summary {{ border-bottom: 1px solid var(--border); }}
    .group-content {{ padding: 1.25rem; }}

    /* Responsive */
    @media (max-width: 600px) {{
        body {{ padding: 1rem; }}
        .tabs {{ flex-direction: column; }}
        .tab-btn {{ border-radius: 0; }}
        .tab-btn:first-child {{ border-radius: 8px 8px 0 0; }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>📚 {html_mod.escape(book_name)}</h1>
    <div class="subtitle">Intellectual Distillation — Generated by BookConvert</div>
</div>

<div class="tabs">
    <button class="tab-btn active" onclick="showTab('short')">⚡ Short Version</button>
    <button class="tab-btn" onclick="showTab('long')">📖 Long Version (Groups)</button>
</div>

<div id="tab-short" class="tab-content active">
    <div class="content" id="final-content"><p class="loading">Rendering...</p></div>
</div>

<div id="tab-long" class="tab-content">
    {groups_html}
</div>

<script>
// ─── Raw markdown data (embedded by Python) ───────────────
const finalMarkdown = `{final_md_escaped}`;
const groupMarkdowns = [
    {groups_js_array}
];

// ─── Render on load ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
    // Configure marked
    marked.setOptions({{
        breaks: true,
        gfm: true,
    }});

    // Render final synthesis
    const finalEl = document.getElementById('final-content');
    if (finalMarkdown.trim()) {{
        finalEl.innerHTML = marked.parse(finalMarkdown);
    }} else {{
        finalEl.innerHTML = '<p class="empty">No final synthesis available yet.</p>';
    }}

    // Render groups (lazy — only when accordion opens)
    document.querySelectorAll('.group-accordion').forEach((el, i) => {{
        el.addEventListener('toggle', () => {{
            if (el.open && groupMarkdowns[i]) {{
                const contentEl = document.getElementById('group-' + i);
                if (contentEl.querySelector('.loading')) {{
                    contentEl.innerHTML = marked.parse(groupMarkdowns[i].md);
                }}
            }}
        }});
    }});
}});

// ─── Tab switching ────────────────────────────────────────
function showTab(name) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    event.target.classList.add('active');
}}
</script>

</body>
</html>"""


def export_html(
    book_dir: Path,
    book_name: str,
    generate_final: bool = True,
) -> Path:
    """Export distillation results to HTML."""
    final_path = book_dir / "final.md" if generate_final else None
    synthesis_dir = book_dir / "synthesis"
    group_files = (
        sorted(synthesis_dir.glob("group_*.md")) if synthesis_dir.exists() else []
    )

    html_content = generate_html(book_name, final_path, group_files)
    html_path = book_dir / "index.html"
    html_path.write_text(html_content, encoding="utf-8")

    print(f"   🌐 Exported → {html_path.name} ({len(html_content):,} bytes)")
    return html_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python export_html.py <book_dir> <book_name>")
        sys.exit(1)

    book_dir = Path(sys.argv[1])
    book_name = sys.argv[2]
    export_html(book_dir, book_name)
