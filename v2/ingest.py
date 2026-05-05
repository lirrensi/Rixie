# FILE: v2/ingest.py
# PURPOSE: Normalize source inputs into a stable V2 source.md representation for downstream cartography.
# OWNS: Format detection, lightweight conversion reuse from V1 patterns, and source text cleanup.
# EXPORTS: ingest_source, detect_format, normalize_text.
# DOCS: v2/process.py, v2/schema.py

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def detect_format(source_path: Path | None) -> str:
    if not source_path:
        return "markdown"
    return source_path.suffix.lower().lstrip(".") or "markdown"


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _read_plain_text(source_path: Path) -> str:
    return source_path.read_text(encoding="utf-8")


def _convert_epub_to_text(source_path: Path, workspace_dir: Path) -> str:
    temp_md = workspace_dir / f"{source_path.stem}.ingested.md"
    try:
        result = subprocess.run(
            ["pandoc", str(source_path), "-t", "markdown", "-o", str(temp_md)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and temp_md.exists():
            return temp_md.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RuntimeError(
            "Could not convert EPUB: pandoc is not installed."
        ) from e
    except Exception as e:
        raise RuntimeError(f"Could not convert EPUB: {e}") from e

    raise RuntimeError("Could not convert EPUB with pandoc.")


def _convert_pdf_to_text(source_path: Path, workspace_dir: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(source_path))
        text_content: list[str] = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()
            if not page_text:
                continue
            if text_content:
                text_content.append("\n\n---\n\n")
            text_content.append(page_text)
        if text_content:
            return "".join(text_content)
    except Exception:
        pass

    temp_md = workspace_dir / f"{source_path.stem}.ingested.md"
    try:
        result = subprocess.run(
            ["pandoc", str(source_path), "-t", "markdown", "-o", str(temp_md)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and temp_md.exists():
            return temp_md.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RuntimeError(
            "Could not convert PDF: install pypdf or pandoc for V2 ingestion."
        ) from e
    except Exception as e:
        raise RuntimeError(f"Could not convert PDF: {e}") from e

    raise RuntimeError("Could not extract text from PDF.")


def ingest_source(source_path: Path | None, workspace_dir: Path) -> str:
    if not source_path:
        return normalize_text("# Source Pending\n\nTODO: add source content for V2 processing.")

    source_format = detect_format(source_path)
    if source_format in {"md", "txt"}:
        return normalize_text(_read_plain_text(source_path))
    if source_format == "epub":
        return normalize_text(_convert_epub_to_text(source_path, workspace_dir))
    if source_format == "pdf":
        return normalize_text(_convert_pdf_to_text(source_path, workspace_dir))

    raise RuntimeError(
        f"V2 ingestion does not support '.{source_format}' yet. Convert it to markdown/text first."
    )
