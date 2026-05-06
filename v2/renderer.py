# FILE: v2/renderer.py
# PURPOSE: Read YAML from workspace → json.dumps → inject into template → write HTML.
# RULE:    Zero processing. Zero transformation. Zero HTML/CSS/JS strings.
#          The template owns everything. Python just replaces a marker.

from __future__ import annotations

import json
from pathlib import Path

import yaml

TEMPLATE_PATH = Path(__file__).parent / "template.html"
DATA_MARKER = "/** DATA_MARKER **/"


def render_outputs(artifact, workspace_dir: Path):
    """Read book.yaml → json.dumps → inject into template → write {slug}.html."""
    slug = artifact.metadata.slug
    book_yaml = workspace_dir / "book.yaml"
    data = yaml.safe_load(book_yaml.read_text(encoding="utf-8"))

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace(DATA_MARKER, json.dumps(data, ensure_ascii=False, indent=2))

    html_path = workspace_dir / f"{slug}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"   ✅ HTML written: {html_path}")

    from v2.schema import StageState
    artifact.stages["render"] = StageState(
        name="render", status="done",
        notes=f"Rendered {slug}.html with raw YAML data inline.",
        outputs={"html": str(html_path.name)},
    )
    return artifact.touch()
