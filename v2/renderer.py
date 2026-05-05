# FILE: v2/renderer.py
# PURPOSE: Render the V2 artifact into a single linear HTML reading experience.
# OWNS: V2 HTML assembly with abstract, core essay, and chapter dropdown details.
# EXPORTS: RENDER_STAGE, render_outputs.

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

from markdown import markdown

from v2.schema import BookArtifact, StageState

RENDER_STAGE = "render"


def _md(text: str) -> str:
    source = (text or "").strip()
    if not source:
        return '<p class="empty">Not available yet.</p>'
    return markdown(source, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])


def _clean_summary_text(text: str, chapter_title: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"^#{1,6}\s+.*?$", "", cleaned, count=1, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"^#{1,6}\s+.*?$", "", cleaned, count=1, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"^\*?(chapter summary|chapter|summary)\*?\s*:\s*", "", cleaned, count=1, flags=re.IGNORECASE).strip()

    title_pattern = re.escape(chapter_title.strip())
    cleaned = re.sub(rf"^\*?{title_pattern}\*?\s*", "", cleaned, count=1, flags=re.IGNORECASE).strip()
    cleaned = re.sub(rf"^\*?(chapter summary|chapter)\*?\s*:\s*\*?{title_pattern}\*?\s*", "", cleaned, count=1, flags=re.IGNORECASE).strip()

    cleaned = re.sub(r"^[:\-–—\s]+", "", cleaned).strip()
    return cleaned


def _build_chapters_html(artifact: BookArtifact) -> str:
    if not artifact.chapters:
        return '<p class="empty">No mapped chapters available yet.</p>'

    parts: list[str] = []
    for chapter in artifact.chapters:
        title = html_mod.escape(chapter.title)
        short_html = _md(_clean_summary_text(chapter.short_summary or "", chapter.title))
        detailed_html = _md(_clean_summary_text(chapter.detailed_summary or "", chapter.title))
        parts.append(
            f"""
            <section class="chapter">
                <h2>{title}</h2>
                <div class="chapter-short content">{short_html}</div>
                <details class="chapter-detail">
                    <summary>Expand detailed summary</summary>
                    <div class="content detail-body">{detailed_html}</div>
                </details>
            </section>
            """
        )
    return "\n".join(parts)


def _build_html(artifact: BookArtifact) -> str:
    title = html_mod.escape(artifact.metadata.title)
    abstract_html = _md(artifact.overview.ultra_dense_summary or "")
    chapters_html = _build_chapters_html(artifact)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rixie V2</title>
<style>
    :root {{
        --bg: #0d1117;
        --surface: #161b22;
        --surface-2: #111827;
        --border: #30363d;
        --text: #e6edf3;
        --text-dim: #8b949e;
        --accent: #58a6ff;
        --accent-2: #7ee787;
        --maxw: 920px;
        --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
        --mono: 'SF Mono', 'Fira Code', Menlo, monospace;
    }}

    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        font-family: var(--font);
        background: var(--bg);
        color: var(--text);
        line-height: 1.65;
        padding: 32px 20px 80px;
    }}
    .page {{
        max-width: var(--maxw);
        margin: 0 auto;
    }}
    h1, h2, h3 {{ line-height: 1.25; }}
    h1 {{
        font-size: 2.3rem;
        margin: 0 0 10px;
        color: var(--accent);
    }}
    h2 {{
        font-size: 1.5rem;
        margin: 0 0 16px;
        color: var(--accent-2);
    }}
    h3 {{
        font-size: 1rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-dim);
        margin: 0 0 10px;
    }}
    p {{ margin: 0 0 1em; }}
    a {{ color: var(--accent); }}
    code {{
        font-family: var(--mono);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.1em 0.4em;
    }}
    pre {{
        overflow-x: auto;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 14px;
    }}
    blockquote {{
        margin: 1em 0;
        padding: 0 0 0 14px;
        border-left: 3px solid var(--accent);
        color: var(--text-dim);
    }}
    hr {{
        border: none;
        border-top: 1px solid var(--border);
        margin: 28px 0;
    }}
    .intro {{
        margin-bottom: 28px;
        padding-bottom: 20px;
        border-bottom: 1px solid var(--border);
    }}
    .subtitle {{
        color: var(--text-dim);
        font-size: 0.95rem;
    }}
    .panel {{
        background: linear-gradient(180deg, var(--surface), var(--surface-2));
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 22px 22px 18px;
        margin: 0 0 24px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.18);
    }}
    .content > *:first-child {{ margin-top: 0; }}
    .content > *:last-child {{ margin-bottom: 0; }}
    .chapter {{
        margin: 0 0 22px;
        padding: 22px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
    }}
    .chapter-detail {{
        margin-top: 16px;
        border-top: 1px solid var(--border);
        padding-top: 14px;
    }}
    .chapter-detail summary {{
        cursor: pointer;
        color: var(--accent);
        font-weight: 600;
        user-select: none;
    }}
    .detail-body {{ margin-top: 16px; }}
    .empty {{ color: var(--text-dim); font-style: italic; }}
    @media (max-width: 700px) {{
        body {{ padding: 18px 12px 48px; }}
        h1 {{ font-size: 1.8rem; }}
        .panel, .chapter {{ padding: 16px; }}
    }}
</style>
</head>
<body>
    <main class="page">
        <header class="intro">
            <h1>{title}</h1>
            <div class="subtitle">Rixie V2 progressive book distillation</div>
        </header>

        <section class="panel abstract">
            <h3>Abstract</h3>
            <div class="content">{abstract_html}</div>
        </section>

        <section class="chapters">
            {chapters_html}
        </section>
    </main>
</body>
</html>
"""


def render_outputs(artifact: BookArtifact, workspace_dir: Path) -> BookArtifact:
    artifact.stages.setdefault(RENDER_STAGE, StageState(name=RENDER_STAGE))
    stage = artifact.stages[RENDER_STAGE]

    html_path = workspace_dir / f"{artifact.metadata.slug}.html"
    html_path.write_text(_build_html(artifact), encoding="utf-8")

    stage.notes = f"Rendered V2 HTML artifact to {html_path.name}."
    stage.status = "done"
    stage.outputs = {
        "html": html_path.name,
        "chapter_count": len(artifact.chapters),
    }
    return artifact.touch()
