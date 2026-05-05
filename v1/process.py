#!/usr/bin/env python3
# FILE: v1/process.py
# PURPOSE: Run the full legacy V1 book distillation pipeline from source ingestion through export.
# OWNS: V1 orchestration, config loading, book discovery, format conversion, and stage execution order.
# EXPORTS: main, process_book.
# DOCS: README.md

"""
BookConvert — One script to distill them all.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v1._paths import REPO_ROOT, resolve_asset_path, resolve_config_path
from v1.chunker import chunk_book
from v1.distiller import distill_book, load_prompt as load_distill_prompt
from v1.export_epub import export_epub
from v1.export_html import export_html
from v1.synthesizer import load_prompt as load_synth_prompt
from v1.synthesizer import synthesize_book

INPUT_DIR = REPO_ROOT / "input"
OUTPUT_DIR = REPO_ROOT / "output" / "v1"
CONFIG_PATH = resolve_config_path()


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def sanitize_name(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:80]


def find_books(input_dir: Path) -> list[Path]:
    books = []
    for ext in ["*.md", "*.epub", "*.txt", "*.pdf"]:
        books.extend(input_dir.glob(ext))
    return sorted(books, key=lambda p: p.name.lower())


def process_book(book_path: Path, config: dict, cli_args: list[str] | None = None) -> bool:
    cli_args = cli_args or []
    book_name = sanitize_name(book_path.name)
    book_dir = OUTPUT_DIR / book_name

    print(f"\n{'═' * 60}")
    print(f"📖 {book_path.name}")
    print(f"   → {book_dir}/")
    print(f"{'═' * 60}")

    if book_path.suffix.lower() == ".epub":
        md_path = _convert_epub(book_path, book_dir)
        if not md_path:
            return False
        book_path = md_path

    if book_path.suffix.lower() == ".pdf":
        md_path = _convert_pdf(book_path, book_dir)
        if not md_path:
            return False
        book_path = md_path

    chunks_dir = book_dir / "chunks"
    distilled_dir = book_dir / "distilled"
    synthesis_dir = book_dir / "synthesis"

    chunking = config.get("chunking", {})
    max_tokens = chunking.get("max_tokens", 8000)
    encoding_model = chunking.get("encoding_model", "gpt-4o-mini")
    output_config = config.get("output", {})
    do_final = output_config.get("generate_final", True)
    do_html = output_config.get("generate_html", True)
    do_epub = output_config.get("generate_epub", True)

    if "--no-final" in cli_args:
        do_final = False
    if "--no-html" in cli_args:
        do_html = False
    if "--no-epub" in cli_args:
        do_epub = False

    print(f"\n{'─' * 40}\nSTEP 1/4: CHUNKING\n{'─' * 40}")
    if chunks_dir.exists() and any(chunks_dir.glob("*.md")):
        print(f"   ✅ Chunks already exist ({len(list(chunks_dir.glob('*.md')))} files) — skipping")
    else:
        chunks = chunk_book(book_path, chunks_dir, max_tokens, encoding_model)
        if not chunks:
            print("   ❌ No chunks generated!")
            return False

    print(f"\n{'─' * 40}\nSTEP 2/4: DISTILLING\n{'─' * 40}")
    distill_prompt = load_distill_prompt(resolve_asset_path("distill_chunk_prompt.md"))
    distill_book(chunks_dir, distilled_dir, config, distill_prompt)

    print(f"\n{'─' * 40}\nSTEP 3/4: SYNTHESIZING\n{'─' * 40}")
    final_prompt = load_synth_prompt(resolve_asset_path("distill_final_prompt.md"))
    stats = synthesize_book(
        distilled_dir,
        synthesis_dir,
        book_dir,
        config,
        final_prompt,
        do_final,
    )

    if do_html:
        print(f"\n{'─' * 40}\nSTEP 4/5: HTML EXPORT\n{'─' * 40}")
        export_html(book_dir, book_name, do_final)
    else:
        print(f"\n{'─' * 40}\nSTEP 4/5: HTML EXPORT (skipped)\n{'─' * 40}")

    if do_epub:
        print(f"\n{'─' * 40}\nSTEP 5/5: EPUB EXPORT\n{'─' * 40}")
        export_epub(book_dir, book_name, do_final)
    else:
        print(f"\n{'─' * 40}\nSTEP 5/5: EPUB EXPORT (skipped)\n{'─' * 40}")

    print(f"\n{'═' * 60}")
    print(f"✅ COMPLETE: {book_name}")
    print(f"   Chunks:    {chunks_dir}/")
    print(f"   Distilled: {distilled_dir}/")
    print(f"   Synthesis: {synthesis_dir}/")
    if do_final and stats.get("final"):
        print(f"   Final:     {book_dir / 'final.md'}")
    if do_html:
        print(f"   HTML:      {book_dir / f'{book_name}.html'}")
    if do_epub:
        print(f"   EPUB:      {book_dir / f'{book_name}.epub'}")
    print(f"{'═' * 60}")
    return True


def _convert_epub(epub_path: Path, book_dir: Path) -> Path | None:
    md_path = book_dir / f"{epub_path.stem}.md"
    if md_path.exists():
        print(f"   ✅ Already converted: {md_path.name}")
        return md_path

    import subprocess

    try:
        print("   📕 Converting EPUB → Markdown (pandoc)...")
        book_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["pandoc", str(epub_path), "-t", "markdown", "-o", str(md_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and md_path.exists():
            print(f"   ✅ Converted: {md_path.name} ({md_path.stat().st_size:,} bytes)")
            return md_path
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"   ⚠️  Pandoc failed: {e}")

    print("   ❌ Could not convert EPUB. Install pandoc: https://pandoc.org/installing.html")
    return None


def _convert_pdf(pdf_path: Path, book_dir: Path) -> Path | None:
    md_path = book_dir / f"{pdf_path.stem}.md"
    if md_path.exists():
        print(f"   ✅ Already converted: {md_path.name}")
        return md_path

    try:
        print("   📕 Converting PDF → Markdown (pypdf)...")
        book_dir.mkdir(parents=True, exist_ok=True)
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        text_content = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                if i > 0:
                    text_content.append("\n\n---\n\n")
                text_content.append(page_text)

        if text_content:
            md_content = "".join(text_content)
            md_path.write_text(md_content, encoding="utf-8")
            print(f"   ✅ Converted: {md_path.name} ({md_path.stat().st_size:,} bytes)")
            return md_path
        print("   ⚠️  No text extracted from PDF")
    except ImportError:
        print("   ⚠️  pypdf not installed, trying pandoc...")
    except Exception as e:
        print(f"   ⚠️  pypdf failed: {e}")

    import subprocess

    try:
        print("   📕 Converting PDF → Markdown (pandoc)...")
        result = subprocess.run(
            ["pandoc", str(pdf_path), "-t", "markdown", "-o", str(md_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and md_path.exists():
            print(f"   ✅ Converted: {md_path.name} ({md_path.stat().st_size:,} bytes)")
            return md_path
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"   ⚠️  Pandoc failed: {e}")

    print("   ❌ Could not convert PDF. Install pypdf or pandoc: https://pypdf.readthedocs.io/")
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if not argv:
        argv = sys.argv[1:]

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  📚 BookConvert — Intellectual Distillation Pipeline     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not CONFIG_PATH.exists():
        print(f"\n⚠️  No {CONFIG_PATH} found — using defaults")
        print("   Create config.yaml to customize LLM settings")

    config = load_config()

    for prompt_file in ["distill_chunk_prompt.md", "distill_final_prompt.md"]:
        prompt_path = resolve_asset_path(prompt_file)
        if not prompt_path.exists():
            print(f"\n❌ Missing: {prompt_file}")
            print("   This file is required. Keep it in v1/ or at the repo root.")
            return 1

    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    specific_books = [Path(a) for a in argv if not a.startswith("--")]
    books = sorted(specific_books, key=lambda p: p.name.lower()) if specific_books else find_books(INPUT_DIR)

    if not books:
        print(f"\n📂 No books found in {INPUT_DIR}/")
        print(f"   Drop .md or .epub files into {INPUT_DIR}/ and run again")
        return 0

    print(f"\n📚 Found {len(books)} book(s) to process")

    success = 0
    failed = 0
    for book_path in books:
        if not book_path.exists():
            print(f"\n❌ Not found: {book_path}")
            failed += 1
            continue

        try:
            if process_book(book_path, config, argv):
                success += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\n\n⏸️  Interrupted! Progress is saved — run again to resume.")
            return 130
        except Exception as e:
            print(f"\n❌ Error processing {book_path.name}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print(f"\n{'═' * 60}")
    print("🏁 ALL DONE")
    print(f"   ✅ Success: {success}")
    if failed:
        print(f"   ❌ Failed:  {failed}")
    print(f"{'═' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
