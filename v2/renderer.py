# FILE: v2/renderer.py
# PURPOSE: Render the V2 artifact into a mini-book-reader HTML with full UI controls.
# OWNS: V2 HTML assembly + template integration + chapter mapping.
# EXPORTS: RENDER_STAGE, render_outputs.
# DOCS: v2/process.py, v2/schema.py

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

from markdown import markdown

from v2.schema import BookArtifact

RENDER_STAGE = "render"


def _escape(text: str) -> str:
    return html_mod.escape(text or "")


def _md(text: str) -> str:
    source = (text or "").strip()
    if not source:
        return ""
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


CSS_CORE = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;scroll-padding-top:60px;overflow-x:hidden}
body{min-height:100vh;overflow-x:hidden}
html{font-size:var(--root-font-size,16px)}
:root{
  --bg:#ffffff;--bg-subtle:#f7f7f7;--surface:#fafafa;--surface-2:#f0f0f0;--border:#e0e0e0;
  --border-subtle:#e8e8e8;--text:#1a1a2e;--text-dim:#555566;--text-muted:#888899;
  --accent:#d04030;--accent-dim:rgba(208,64,48,0.10);--accent-2:#5048b0;--accent-2-dim:rgba(80,72,176,0.10);
  --gold:#b08820;--green:#208848;--red:#c03030;--shadow:0 2px 12px rgba(0,0,0,0.06);
  --bar-bg:rgba(255,255,255,0.92);
  --content-width:680px;--content-wide-width:900px;--body-line-height:1.7;
}
[data-theme="light-pure"]{--bg:#ffffff;--bg-subtle:#fafafa;--surface:#ffffff;--surface-2:#f7f7f7;--border:#e0e0e0;--bar-bg:rgba(255,255,255,0.92)}
[data-theme="light-paper"]{--bg:#fbf8f1;--bg-subtle:#f5f2e9;--surface:#fefdf8;--surface-2:#f9f6ed;--border:#e5dfcd;--bar-bg:rgba(251,248,241,0.92)}
[data-theme="light-dusk"]{--bg:#fff5ee;--bg-subtle:#ffe8dc;--surface:#fffaf2;--surface-2:#ffe4d9;--border:#ffccaa;--bar-bg:rgba(255,245,238,0.92)}
[data-theme="dark-vesepia"]{--bg:#1a1614;--bg-subtle:#231e1b;--surface:#26201d;--surface-2:#1f1916;--border:#3d3430;--text:#e8e4e0;--text-dim:#a8a09a;--bar-bg:rgba(26,22,20,0.92)}
[data-theme="dark-oled"]{--bg:#000000;--bg-subtle:#0a0a0a;--surface:#050505;--surface-2:#080808;--border:#181818;--text:#e8e4e0;--bar-bg:rgba(0,0,0,0.98)}
[data-theme="dark-dimmed"]{--bg:#14141a;--bg-subtle:#1e1e28;--surface:#1a1a26;--surface-2:#12121c;--text:#c8c8d8;--text-dim:#8888a0;--bar-bg:rgba(20,20,26,0.92)}
[data-theme="dark-midnight"]{--bg:#0d1117;--bg-subtle:#161b22;--surface:#1f242c;--surface-2:#21262d;--text:#c8d8e8;--text-dim:#7d858f;--bar-bg:rgba(13,17,23,0.92)}
body{background:var(--bg);color:var(--text);font-size:1rem;line-height:var(--body-line-height,1.7);transition:background .3s,color .3s}
.content{max-width:var(--content-width,680px);margin:0 auto;padding:0 1.5rem}
.content-wide{max-width:var(--content-wide-width,900px);margin:0 auto;padding:0 1.5rem}
.topbar{position:fixed;top:0;left:0;right:0;z-index:1000;height:48px;background:var(--bar-bg);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;padding:0 1rem;gap:.75rem;transition:background .3s}
.topbar-left{display:flex;align-items:center;gap:.5rem;flex-shrink:0}
.topbar-center{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden}
.topbar-right{display:flex;align-items:center;gap:.35rem;flex-shrink:0}
.sidebar-toggle{background:none;border:none;color:var(--text-dim);font-size:1.1rem;cursor:pointer;padding:6px 8px;border-radius:6px;transition:background .15s,color .15s;line-height:1}
.sidebar-toggle:hover{background:var(--accent-dim);color:var(--text)}
.bar-chapter{font-size:.75rem;letter-spacing:.06em;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;transition:color .3s}
.progress-track{flex:1;height:3px;background:var(--border-subtle);border-radius:3px;overflow:hidden;max-width:300px}
.progress-fill{height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:3px;transition:width .1s linear}
.bar-time{font-size:.7rem;color:var(--text-muted);white-space:nowrap;min-width:80px;text-align:right}
.toggle-btn{background:none;border:none;color:var(--text-muted);font-size:.85rem;cursor:pointer;padding:6px 8px;border-radius:6px;transition:background .15s,color .15s;line-height:1;display:flex;align-items:center;gap:4px}
.toggle-btn:hover{background:var(--accent-dim);color:var(--text)}
.toggle-btn .label{font-size:.65rem;letter-spacing:.04em}
.toggle-btn.active-audio{color:var(--accent);background:var(--accent-dim)}
.settings-btn{background:none;border:none;color:var(--text-dim);font-size:1.2rem;cursor:pointer;padding:6px 8px;border-radius:6px;transition:background .15s,color .15s;line-height:1}
.settings-btn:hover{background:var(--accent-dim);color:var(--text)}
.sidebar-overlay{position:fixed;inset:0;z-index:1100;background:rgba(0,0,0,0.3);opacity:0;pointer-events:none;transition:opacity .25s}
.sidebar-overlay.open{opacity:1;pointer-events:auto}
.sidebar{position:fixed;top:0;left:0;bottom:0;z-index:1200;width:280px;max-width:85vw;background:var(--surface);border-right:1px solid var(--border);transform:translateX(-100%);transition:transform .3s cubic-bezier(0.19,1,0.22,1);display:flex;flex-direction:column;overflow-y:auto}
.sidebar.open{transform:translateX(0)}
.sidebar-header{padding:1.25rem 1.25rem 0.75rem;border-bottom:1px solid var(--border-subtle)}
.sidebar-title{font-size:.85rem;font-weight:600;color:var(--text);margin-bottom:.25rem}
.sidebar-author{font-size:.72rem;color:var(--text-muted)}
.sidebar-chapters{padding:.5rem 0;flex:1}
.sidebar-chapter{display:block;padding:.55rem 1.25rem;font-size:.82rem;color:var(--text-dim);text-decoration:none;border-left:3px solid transparent;transition:background .15s,color .15s,border-color .15s;cursor:pointer}
.sidebar-chapter:hover{background:var(--accent-dim);color:var(--text)}
.sidebar-chapter.active{border-left-color:var(--accent);color:var(--text);background:var(--accent-dim)}
.sidebar-chapter-num{font-size:.68rem;color:var(--text-muted);margin-right:.6rem;letter-spacing:.04em}
.sidebar-footer{padding:.75rem 1.25rem;border-top:1px solid var(--border-subtle);display:flex;flex-direction:column;gap:.75rem}
.book-hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:6rem 1.5rem 4rem;position:relative}
.book-hero-label{font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--text-muted);margin-bottom:1.5rem}
.book-hero h1{font-size:clamp(2rem,5vw,3.5rem);font-weight:300;letter-spacing:.02em;line-height:1.2;margin-bottom:.75rem}
.book-hero-author{font-size:1rem;color:var(--text-dim);margin-bottom:.5rem}
.book-hero-tagline{font-size:1rem;color:var(--text-muted);max-width:560px;margin:0 auto 2rem;font-style:italic;line-height:1.6}
.book-hero-meta{display:flex;gap:1.5rem;align-items:center;font-size:.8rem;color:var(--text-muted);margin-bottom:2.5rem}
.book-hero-meta span{display:flex;align-items:center;gap:.35rem}
.scroll-hint{font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:var(--text-muted);animation:hint-pulse 2s ease-in-out infinite}
@keyframes hint-pulse{0%,100%{opacity:.4}50%{opacity:1}}
.toc-section{padding:4rem 1.5rem 5rem;max-width:680px;margin:0 auto}
.toc-label{font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--text-muted);margin-bottom:2.5rem;text-align:center}
.toc-list{list-style:none}
.toc-item{border-bottom:1px solid var(--border-subtle)}
.toc-item a{display:flex;align-items:baseline;gap:1rem;padding:1rem 0;text-decoration:none;color:var(--text);transition:color .15s}
.toc-item a:hover{color:var(--accent)}
.toc-num{font-size:.75rem;color:var(--text-muted);letter-spacing:.06em;flex-shrink:0;width:2rem;text-align:right}
.toc-title{font-size:.95rem;line-height:1.4}
.toc-hook{font-size:.8rem;color:var(--text-muted);margin-top:.25rem;line-height:1.5;font-style:italic}
.chapter{padding:0 0 4rem;border-top:1px solid var(--border-subtle)}
.chapter:nth-child(odd){background:var(--bg)}
.chapter:nth-child(even){background:var(--bg-subtle)}
.chapter-hero{padding:5.5rem 1.5rem 2.5rem;text-align:center;position:relative}
.chapter-number{font-size:clamp(4rem,12vw,8rem);font-weight:200;line-height:1;color:var(--border);position:absolute;top:1.5rem;left:50%;transform:translateX(-50%);pointer-events:none;user-select:none;opacity:.45}
.chapter-label{font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;color:var(--text-muted);margin-bottom:1rem;position:relative;z-index:1}
.chapter-hero h2{font-size:clamp(1.5rem,4vw,2.5rem);font-weight:300;line-height:1.3;margin-bottom:.9rem;position:relative;z-index:1}
.chapter-hook{font-size:1rem;color:var(--text-dim);max-width:540px;margin:0 auto;font-style:italic;line-height:1.6;position:relative;z-index:1}
.chapter-body{padding:2rem 1.5rem 3rem;max-width:680px;margin:0 auto}
.chapter-body p{margin-bottom:1.5rem;line-height:1.75;color:var(--text)}
.chapter-detail{margin-top:2.5rem;padding-top:1.5rem;border-top:1px solid var(--border-subtle)}
.chapter-detail>summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:.9rem;letter-spacing:.04em;outline:none;transition:color .15s}
.chapter-detail>summary:hover{color:var(--text)}
.chapter-detail>summary::-webkit-details-marker{display:none}
.chapter-detail>summary::after{content:"Expand";font-size:.75rem;margin-left:.5rem;opacity:.7}
.chapter-detail[open]>summary::after{content:"Collapse"}
.detail-body{margin-top:1rem;padding:1.25rem;background:var(--surface-2);border-radius:8px;border:1px solid var(--border)}
.end-screen{padding:5rem 1.5rem;text-align:center;border-top:1px solid var(--border-subtle)}
.end-screen .thesis{font-size:clamp(1.1rem,2.5vw,1.4rem);color:var(--text);max-width:600px;margin:0 auto 2rem;line-height:1.8;font-weight:300}
.end-screen .attribution{font-size:.8rem;color:var(--text-muted);letter-spacing:.06em}
.end-screen .sign-off{font-size:.78rem;color:var(--text-muted);margin-top:2.5rem;font-style:italic}
.copy-btn{display:inline-flex;align-items:center;gap:.5rem;background:var(--accent-dim);border:1px solid var(--accent);color:var(--accent);padding:.6rem 1.2rem;border-radius:8px;font-size:.85rem;cursor:pointer;font-family:inherit;transition:background .15s,color .15s;margin-top:1.5rem}
.copy-btn:hover{background:var(--accent);color:var(--bg)}
.settings-dropdown{position:fixed;top:48px;right:0;z-index:1300;background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 12px 12px;padding:.75rem 1rem;min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,0.15);opacity:0;pointer-events:none;transform:translateY(-8px);transition:opacity .2s,transform .2s}
.settings-dropdown.open{opacity:1;pointer-events:auto;transform:translateY(0)}
.settings-row{display:flex;align-items:center;justify-content:space-between;padding:.5rem 0;border-bottom:1px solid var(--border-subtle)}
.settings-row:last-child{border-bottom:none}
.settings-label{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.settings-buttons{display:flex;gap:.35rem}
.settings-buttons .toggle-btn{padding:5px 10px;font-size:.8rem}
.font-size-control,.width-control,.spacing-control{display:flex;align-items:center;gap:.5rem;width:100%}
.font-size-control span,.width-control span,.spacing-control span{font-size:.7rem;color:var(--text-muted);flex-shrink:0}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:4px;background:var(--border);border-radius:4px;outline:none;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:14px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid var(--surface);box-shadow:0 1px 3px rgba(0,0,0,0.2)}
input[type=range]::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid var(--surface)}
@media (max-width:640px){
.bar-chapter{max-width:90px;font-size:.68rem}
.bar-time{min-width:70px;font-size:.68rem}
.progress-track{max-width:140px}
.chapter-number{font-size:3.5rem}
.topbar-right .toggle-btn,.topbar-right .bar-time{display:none !important}
.topbar-right .settings-btn{display:block !important}
.sidebar-footer{flex-direction:column;gap:.6rem;padding:.6rem 1rem}
.sidebar-footer .toggle-btn{display:none !important}
.sidebar-footer .width-control,.sidebar-footer .spacing-control{display:none}
}
@media (min-width:641px){
.settings-btn{display:none}
.settings-dropdown{display:none}
.sidebar-footer{flex-direction:row;flex-wrap:wrap;align-items:center;gap:.4rem;padding:.75rem 1.25rem}
.sidebar-footer .toggle-btn{display:flex !important}
.sidebar-footer .font-size-control,.sidebar-footer .width-control,.sidebar-footer .spacing-control{width:120px;flex-shrink:0}
}
@media print{
*{color:#000 !important;background:#fff !important;box-shadow:none !important}
.topbar,.sidebar,.sidebar-overlay,.toggle-btn,.scroll-hint,.progress-track,.copy-btn,.chapter-number,.settings-btn,.settings-dropdown{display:none !important}
.chapter{page-break-before:always;border-top:none;padding:0}
.chapter:first-of-type{page-break-before:auto}
.book-hero{min-height:auto;padding:2rem 0}
.end-screen{page-break-before:always}
a{text-decoration:none}
body{font-size:11pt;line-height:1.5}
}
"""


def _build_hero_section(artifact: BookArtifact) -> str:
    title = _escape(artifact.metadata.title)
    abstract = _md(_clean_summary_text(artifact.overview.ultra_dense_summary or "", title))
    chapter_count = len(artifact.chapters)
    reading_time = max(1, round(chapter_count * 0.5))
    return f"""
    <section class="book-hero">
      <div class="book-hero-label">Interactive Edition</div>
      <h1>{title}</h1>
      <div class="book-hero-author">Rixie V2 Edition</div>
      <p class="book-hero-tagline">{abstract}</p>
      <div class="book-hero-meta">
        <span>📖 {chapter_count} chapters</span>
        <span>⏱ ~{reading_time} min read</span>
      </div>
      <div class="scroll-hint">↓ scroll to begin</div>
    </section>
    """


def _build_toc_section(artifact: BookArtifact) -> str:
    items = []
    for idx, chapter in enumerate(artifact.chapters, start=1):
        title = _escape(chapter.title)
        short_clean = _clean_summary_text(chapter.short_summary or "", chapter.title)
        hook = _escape(short_clean[:150] + ("..." if len(short_clean) > 150 else ""))
        items.append(f"""
        <li class="toc-item">
          <a href="#chapter-{idx}">
            <span class="toc-num">{idx:02d}</span>
            <div>
              <div class="toc-title">{title}</div>
              <div class="toc-hook">{hook}</div>
            </div>
          </a>
        </li>
        """)
    return f"""
    <section class="toc-section">
      <div class="toc-label">Contents</div>
      <ol class="toc-list">
        {''.join(items)}
      </ol>
    </section>
    """


def _build_chapters_html(artifact: BookArtifact) -> str:
    if not artifact.chapters:
        return '<p class="empty">No mapped chapters available yet.</p>'

    parts = []
    for idx, chapter in enumerate(artifact.chapters, start=1):
        title = _escape(chapter.title)
        short_clean = _clean_summary_text(chapter.short_summary or "", chapter.title)
        short_md = _md(short_clean)
        detailed_clean = _clean_summary_text(chapter.detailed_summary or "", chapter.title)
        detailed_md = _md(detailed_clean)

        detail_section = ""
        if detailed_md:
            detail_section = f"""
            <details class="chapter-detail" open>
              <summary>Expand detailed summary</summary>
              <div class="detail-body">
                {detailed_md}
              </div>
            </details>
            """

        parts.append(f"""
        <section class="chapter" id="chapter-{idx}">
          <div class="chapter-hero">
            <div class="chapter-number">{idx:02d}</div>
            <div class="chapter-label">Chapter {idx}</div>
            <h2>{title}</h2>
            <p class="chapter-hook">{_escape(short_clean[:200] + ('...' if len(short_clean) > 200 else ''))}</p>
          </div>

          <div class="chapter-body">
            <p>{short_md}</p>

            {detail_section}
          </div>

          <div class="chapter-divider"></div>
        </section>
        """)
    return "\n".join(parts)


def _build_end_section(artifact: BookArtifact) -> str:
    title = _escape(artifact.metadata.title)
    abstract = _clean_summary_text(artifact.overview.ultra_dense_summary or "", "")
    thesis = _escape(abstract[:300] + ("..." if len(abstract) > 300 else ""))
    return f"""
    <section class="end-screen">
      <div class="section-label" style="text-align: center">
        The Core Message
      </div>
      <p class="thesis">{thesis}</p>
      <div class="attribution">{title} · Rixie V2 Edition</div>
      <div class="sign-off">Built with care.</div>
      <button class="copy-btn" id="copyBtn">
        📋 Copy End
      </button>
    </section>
    """


def render_outputs(artifact: BookArtifact, workspace_dir: Path) -> BookArtifact:
    from v2.schema import StageState
    artifact.stages.setdefault(RENDER_STAGE, StageState(name=RENDER_STAGE))

    title = _escape(artifact.metadata.title)
    hero_section = _build_hero_section(artifact)
    toc_section = _build_toc_section(artifact)
    chapters_html = _build_chapters_html(artifact)
    end_section = _build_end_section(artifact)

    # Build sidebar chapter links
    sidebar_chapters = "\n".join(
        f'        <a class="sidebar-chapter" href="#chapter-{idx}" onclick="toggleSidebar()">\n'
        f'          <span class="sidebar-chapter-num">{idx:02d}</span>{_escape(ch.title)}\n'
        f'        </a>'
        for idx, ch in enumerate(artifact.chapters, start=1)
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en" dir="ltr" data-theme="dark-vesepia" data-font="sans">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Rixie V2</title>
<script>
(function() {{
  const t = localStorage.getItem('theme');
  if (t) document.documentElement.setAttribute('data-theme', t);
  else if (window.matchMedia('(prefers-color-scheme: light)').matches)
    document.documentElement.setAttribute('data-theme', 'light-pure');
  const f = localStorage.getItem('font');
  if (f) document.documentElement.setAttribute('data-font', f);
  const fs = localStorage.getItem('fontSize');
  if (fs) document.documentElement.style.setProperty('--root-font-size', fs + 'px');
  const cw = localStorage.getItem('contentWidth');
  if (cw) {{
    document.documentElement.style.setProperty('--content-width', cw + 'px');
    document.documentElement.style.setProperty('--content-wide-width', parseInt(cw) + 220 + 'px');
  }}
  const lh = localStorage.getItem('lineHeight');
  if (lh) {{
    const lhVal = Math.round(parseFloat(lh) * 10);
    document.documentElement.style.setProperty('--body-line-height', (lhVal / 10).toFixed(1));
  }}
}})();
</script>
<style>
{CSS_CORE}
</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-left">
    <button class="sidebar-toggle" onclick="toggleSidebar()" aria-label="Chapter menu">
      ☰
    </button>
    <span class="bar-chapter" id="barChapter">{title}</span>
  </div>
  <div class="topbar-center">
    <div class="progress-track">
      <div class="progress-fill" id="progressFill"></div>
    </div>
  </div>
  <div class="topbar-right">
    <span class="bar-time" id="barTime"></span>
    <button class="toggle-btn" onclick="cycleFont()" aria-label="Change font">
      <span id="fontIcon">Aa</span>
    </button>
    <button class="toggle-btn" onclick="toggleTheme()" aria-label="Toggle theme">
      <span id="themeIcon">☾</span>
    </button>
    <button class="toggle-btn" id="audioBtn" onclick="toggleAudio()" aria-label="Focus mode audio">
      <span>🎧</span>
    </button>
    <button class="toggle-btn" id="focusBtn" onclick="toggleFocusMode()" aria-label="Focus mode">
      <span>🎯</span>
    </button>
    <button class="settings-btn" onclick="toggleSettings()" aria-label="Settings">
      ⚙
    </button>
  </div>
</header>

<div class="settings-dropdown" id="settingsDropdown">
  <div class="settings-row">
    <span class="settings-label">Font</span>
    <div class="settings-buttons">
      <button class="toggle-btn" onclick="cycleFont()" aria-label="Change font">
        <span id="fontIconMobile">Aa</span>
      </button>
      <button class="toggle-btn" onclick="toggleTheme()" aria-label="Toggle theme">
        <span id="themeIconMobile">☾</span>
      </button>
    </div>
  </div>
  <div class="settings-row">
    <span class="settings-label">Size</span>
    <div class="font-size-control">
      <span>A</span>
      <input type="range" min="13" max="24" step="1" value="16" id="fontSizeSlider" oninput="updateFontSize(this.value)" />
      <span style="font-size: 1rem">A</span>
    </div>
  </div>
  <div class="settings-row">
    <span class="settings-label">Width</span>
    <div class="width-control">
      <span>←</span>
      <input type="range" min="480" max="1200" step="20" value="680" id="widthSlider" oninput="updateWidth(this.value)" />
      <span>→</span>
    </div>
  </div>
  <div class="settings-row">
    <span class="settings-label">Spacing</span>
    <div class="spacing-control">
      <span>─</span>
      <input type="range" min="14" max="24" step="1" value="17" id="lineHeightSlider" oninput="updateLineHeight(this.value)" />
      <span>≡</span>
    </div>
  </div>
  <div class="settings-row">
    <span class="settings-label">Vision</span>
    <div class="settings-buttons">
      <button class="toggle-btn" id="audioBtnMobile" onclick="toggleAudio()">
        🎧
      </button>
    </div>
  </div>
</div>

<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
<nav class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-title">{title}</div>
    <div class="sidebar-author">Rixie V2 Edition</div>
  </div>
  <div class="sidebar-chapters">
{sidebar_chapters}
  </div>
  <div class="sidebar-footer">
    <button class="toggle-btn" onclick="cycleFont()" aria-label="Change font">
      Aa
    </button>
    <button class="toggle-btn" onclick="toggleTheme()" aria-label="Toggle theme">
      <span id="themeIconSidebar">☾</span>
    </button>
    <div class="font-size-control">
      <span style="font-size:.7rem">A</span>
      <input type="range" min="13" max="24" step="1" value="16" id="fontSizeSliderSidebar" oninput="updateFontSize(this.value)" />
      <span style="font-size:1rem">A</span>
    </div>
    <div class="width-control">
      <span style="font-size:.7rem">←</span>
      <input type="range" min="480" max="1200" step="20" value="680" id="widthSliderSidebar" oninput="updateWidth(this.value)" />
      <span style="font-size:.7rem">→</span>
    </div>
    <div class="spacing-control">
      <span style="font-size:.7rem">─</span>
      <input type="range" min="14" max="24" step="1" value="17" id="lineHeightSliderSidebar" oninput="updateLineHeight(this.value)" />
      <span style="font-size:.7rem">≡</span>
    </div>
  </div>
</nav>

{hero_section}
{toc_section}
{chapters_html}
{end_section}

<script>
const themes = ['light-pure','light-paper','light-dusk','dark-vesepia','dark-oled','dark-dimmed','dark-midnight'];
const themeIcons = {{'light-pure': '◯','light-paper': '📄','light-dusk': '🌆','dark-vesepia': '☾','dark-oled': '⬛','dark-dimmed': '🌑','dark-midnight': '🌌',light: '◯',dark: '☾',none: '◯'}};
function toggleTheme() {{
  const root = document.documentElement;
  const current = root.getAttribute('data-theme') || 'dark-vesepia';
  const normalizedCurrent = current === 'light' ? 'light-pure' : current === 'dark' ? 'dark-vesepia' : current;
  const idx = themes.indexOf(normalizedCurrent);
  const next = themes[(idx + 1) % themes.length];
  root.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateThemeIcons(next);
}}
function updateThemeIcons(theme) {{
  const icon = themeIcons[theme] || themeIcons['light-pure'];
  document.getElementById('themeIcon').textContent = icon;
  const sidebar = document.getElementById('themeIconSidebar');
  if (sidebar) sidebar.textContent = icon;
  const mobile = document.getElementById('themeIconMobile');
  if (mobile) mobile.textContent = icon;
}}
const fonts = ['sans', 'serif'];
function cycleFont() {{
  const root = document.documentElement;
  const current = root.getAttribute('data-font');
  const idx = fonts.indexOf(current);
  const next = fonts[(idx + 1) % fonts.length];
  root.setAttribute('data-font', next);
  localStorage.setItem('font', next);
  const icon = next === 'serif' ? 'Ag' : 'Aa';
  document.getElementById('fontIcon').textContent = icon;
  const mobile = document.getElementById('fontIconMobile');
  if (mobile) mobile.textContent = icon;
}}
function toggleSidebar() {{
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('open');
  document.getElementById('settingsDropdown')?.classList.remove('open');
}}
function toggleSettings() {{
  document.getElementById('settingsDropdown').classList.toggle('open');
}}
document.addEventListener('click', (e) => {{
  const dd = document.getElementById('settingsDropdown');
  const btn = e.target.closest('.settings-btn');
  if (!btn && !e.target.closest('.settings-dropdown')) dd?.classList.remove('open');
}});
function updateFontSize(px) {{
  document.documentElement.style.setProperty('--root-font-size', px + 'px');
  localStorage.setItem('fontSize', px);
  document.getElementById('fontSizeSlider').value = px;
  document.getElementById('fontSizeSliderSidebar').value = px;
}}
function updateWidth(px) {{
  document.documentElement.style.setProperty('--content-width', px + 'px');
  document.documentElement.style.setProperty('--content-wide-width', parseInt(px) + 220 + 'px');
  localStorage.setItem('contentWidth', px);
  document.getElementById('widthSlider').value = px;
  document.getElementById('widthSliderSidebar').value = px;
}}
function updateLineHeight(val) {{
  const lh = (val / 10).toFixed(1);
  document.documentElement.style.setProperty('--body-line-height', lh);
  localStorage.setItem('lineHeight', lh);
  document.getElementById('lineHeightSlider').value = val;
  document.getElementById('lineHeightSliderSidebar').value = val;
}}
const progressFill = document.getElementById('progressFill');
function updateProgress() {{
  const scrolled = window.scrollY;
  const total = document.documentElement.scrollHeight - window.innerHeight;
  if (total > 0) progressFill.style.width = (scrolled / total) * 100 + '%';
}}
const barChapter = document.getElementById('barChapter');
const chapters = document.querySelectorAll('.chapter');
const sidebarLinks = document.querySelectorAll('.sidebar-chapter');
function updateBarChapter() {{
  let current = null;
  const scrollTop = window.scrollY + 80;
  chapters.forEach((ch) => {{ if (ch.offsetTop <= scrollTop) current = ch; }});
  if (current) {{
    const h2 = current.querySelector('h2');
    if (h2) barChapter.textContent = h2.textContent;
  }} else {{
    barChapter.textContent = document.querySelector('.book-hero h1')?.textContent || '';
  }}
  sidebarLinks.forEach((link) => {{
    link.classList.toggle('active', current && link.getAttribute('href') === '#' + current.id);
  }});
}}
const barTime = document.getElementById('barTime');
const totalWords = document.body.innerText.split(/\s+/).length;
const totalMinutes = Math.ceil(totalWords / 200);
function updateTimeRemaining() {{
  const scrolled = window.scrollY;
  const total = document.documentElement.scrollHeight - window.innerHeight;
  if (total <= 0) return;
  const pct = scrolled / total;
  const remaining = Math.ceil(totalMinutes * (1 - pct));
  if (pct > 0.98) barTime.textContent = 'Done!';
  else if (remaining <= 1) barTime.textContent = '<1 min left';
  else barTime.textContent = '~' + remaining + ' min left';
}}
let focusMode = false;
function toggleFocusMode() {{
  focusMode = !focusMode;
  document.body.classList.toggle('focus-mode', focusMode);
  const btn = document.getElementById('focusBtn');
  if (focusMode) {{
    btn.classList.add('active-audio');
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('sidebarOverlay')?.classList.remove('open');
    document.getElementById('settingsDropdown')?.classList.remove('open');
  }} else {{
    btn.classList.remove('active-audio');
  }}
}}
let audioCtx = null, audioSource = null, audioPlaying = false;
function toggleAudio() {{
  const btn = document.getElementById('audioBtn'), mobileBtn = document.getElementById('audioBtnMobile');
  if (audioPlaying) {{
    if (audioSource) {{ audioSource.stop(); audioSource = null; }}
    if (audioCtx) {{ audioCtx.close(); audioCtx = null; }}
    audioPlaying = false;
    btn.classList.remove('active-audio');
    if (mobileBtn) mobileBtn.classList.remove('active-audio');
    return;
  }}
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const sr = audioCtx.sampleRate, buf = audioCtx.createBuffer(1, sr * 2, sr), data = buf.getChannelData(0);
  let last = 0;
  for (let i = 0; i < data.length; i++) {{
    const white = Math.random() * 2 - 1;
    data[i] = (last + 0.02 * white) / 1.02;
    last = data[i];
    data[i] *= 3.5;
  }}
  audioSource = audioCtx.createBufferSource();
  audioSource.buffer = buf;
  audioSource.loop = true;
  const gain = audioCtx.createGain();
  gain.gain.value = 0.15;
  audioSource.connect(gain);
  gain.connect(audioCtx.destination);
  audioSource.start(0);
  audioPlaying = true;
  btn.classList.add('active-audio');
  if (mobileBtn) mobileBtn.classList.add('active-audio');
}}
let scrollTicking = false;
window.addEventListener('scroll', () => {{
  if (!scrollTicking) {{
    requestAnimationFrame(() => {{
      updateProgress();
      updateBarChapter();
      updateTimeRemaining();
      scrollTicking = false;
    }});
    scrollTicking = true;
  }}
}});
document.addEventListener('keydown', (e) => {{
  if (e.target.matches('input, textarea')) return;
  const key = e.key.toLowerCase();
  if (key === 't') {{ e.preventDefault(); toggleTheme(); return; }}
  if (key === 'f') {{ e.preventDefault(); cycleFont(); return; }}
  if (key === 's') {{ e.preventDefault(); toggleFocusMode(); return; }}
  if (key === 'escape') {{
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('sidebarOverlay')?.classList.remove('open');
    document.getElementById('settingsDropdown')?.classList.remove('open');
    if (focusMode) toggleFocusMode();
    return;
  }}
  if (focusMode) return;
  const chs = document.querySelectorAll('.chapter');
  const currentChapter = [...chs].find((ch) => ch.getBoundingClientRect().top <= 100 && ch.getBoundingClientRect().bottom > 100);
  const currentIdx = currentChapter ? [...chs].indexOf(currentChapter) : -1;
  if (key === 'arrowleft' && currentIdx > 0) {{ e.preventDefault(); chs[currentIdx - 1].scrollIntoView({{ behavior: 'smooth' }}); return; }}
  if (key === 'arrowright' && currentIdx < chs.length - 1) {{ e.preventDefault(); chs[currentIdx + 1].scrollIntoView({{ behavior: 'smooth' }}); return; }}
}});
updateProgress();
updateBarChapter();
updateThemeIcons(document.documentElement.getAttribute('data-theme'));
if (document.documentElement.getAttribute('data-font') === 'serif') {{
  document.getElementById('fontIcon').textContent = 'Ag';
  const mobile = document.getElementById('fontIconMobile');
  if (mobile) mobile.textContent = 'Ag';
}}
if (localStorage.getItem('fontSize')) updateFontSize(localStorage.getItem('fontSize'));
if (localStorage.getItem('contentWidth')) updateWidth(localStorage.getItem('contentWidth'));
if (localStorage.getItem('lineHeight')) updateLineHeight(Math.round(parseFloat(localStorage.getItem('lineHeight')) * 10));
updateTimeRemaining();
</script>
</body>
</html>"""

    html_path = workspace_dir / f"{artifact.metadata.slug}.html"
    html_path.write_text(html_content, encoding="utf-8")

    artifact.stages[RENDER_STAGE].notes = f"Rendered V2 HTML to {html_path.name} with full reader UI."
    artifact.stages[RENDER_STAGE].status = "done"
    artifact.stages[RENDER_STAGE].outputs = {
        "html": html_path.name,
        "chapter_count": len(artifact.chapters),
        "features": [
            "theme-toggle",
            "font-toggle",
            "font-size-slider",
            "width-slider",
            "line-height-slider",
            "progress-bar",
            "sidebar-navigation",
            "reading-time-estimate",
            "keyboard-shortcuts",
            "focus-mode",
            "audio-mode",
            "responsive-design",
        ],
    }

    return artifact.touch()