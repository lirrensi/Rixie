#!/usr/bin/env python3
"""
BookConvert — One script to distill them all.

Usage:
    python process.py                    # Process all books in input/
    python process.py input/book.md      # Process a specific book
    python process.py --no-html          # Skip HTML export
    python process.py --no-epub          # Skip EPUB export
    python process.py --no-final         # Skip final merge step
    python process.py --resume           # Resume where left off (default behavior)

Directory structure:
    input/                  → Drop books here (.md, .epub, .pdf, .txt)
    output/{book_name}/
        ├── chunks/         → Smart chunks
        ├── distilled/      → Individual distillations
        ├── synthesis/      → Group distillations
        ├── final.md        → Final synthesis (if enabled)
        ├── {book_name}.html  → HTML export (if enabled)
        └── {book_name}.epub  → EPUB export (if enabled)

Config:
    config.yaml             → LLM params (base_url, api_key, model, temperature)
    distill_chunk_prompt.md → Per-chapter distillation prompt (outputs tagged list)
    distill_final_prompt.md → Final synthesis prompt (list → readable article)
"""

import sys
import re
from pathlib import Path
from datetime import datetime

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from chunker import chunk_book
from distiller import distill_book, load_prompt as load_distill_prompt
from synthesizer import synthesize_book, load_prompt as load_synth_prompt
from export_html import export_html
from export_epub import export_epub


INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
CONFIG_PATH = Path("config.yaml")


def load_config() -> dict:
    """Load configuration from YAML."""
    if CONFIG_PATH.exists():
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def sanitize_name(filename: str) -> str:
    """Convert filename to a clean directory name."""
    name = Path(filename).stem
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:80]


def find_books(input_dir: Path) -> list[Path]:
    """Find all book files in input directory, sorted alphabetically."""
    books = []
    for ext in ["*.md", "*.epub", "*.txt", "*.pdf"]:
        books.extend(input_dir.glob(ext))
    return sorted(books, key=lambda p: p.name.lower())


def process_book(book_path: Path, config: dict) -> bool:
    """Process a single book through the entire pipeline."""
    book_name = sanitize_name(book_path.name)
    book_dir = OUTPUT_DIR / book_name

    print(f"\n{'═' * 60}")
    print(f"📖 {book_path.name}")
    print(f"   → {book_dir}/")
    print(f"{'═' * 60}")

    # Convert EPUB to markdown if needed
    if book_path.suffix.lower() == ".epub":
        md_path = _convert_epub(book_path, book_dir)
        if not md_path:
            return False
        book_path = md_path

    # Convert PDF to markdown if needed
    if book_path.suffix.lower() == ".pdf":
        md_path = _convert_pdf(book_path, book_dir)
        if not md_path:
            return False
        book_path = md_path

    chunks_dir = book_dir / "chunks"
    distilled_dir = book_dir / "distilled"
    synthesis_dir = book_dir / "synthesis"

    # Load settings
    chunking = config.get("chunking", {})
    max_tokens = chunking.get("max_tokens", 8000)
    encoding_model = chunking.get("encoding_model", "gpt-4o-mini")
    output_config = config.get("output", {})
    do_final = output_config.get("generate_final", True)
    do_html = output_config.get("generate_html", True)
    do_epub = output_config.get("generate_epub", True)

    # CLI overrides
    if "--no-final" in sys.argv:
        do_final = False
    if "--no-html" in sys.argv:
        do_html = False
    if "--no-epub" in sys.argv:
        do_epub = False

    # ─── Step 1: Chunk ──────────────────────────────────────
    print(f"\n{'─' * 40}")
    print("STEP 1/4: CHUNKING")
    print(f"{'─' * 40}")

    if chunks_dir.exists() and any(chunks_dir.glob("*.md")):
        print(
            f"   ✅ Chunks already exist ({len(list(chunks_dir.glob('*.md')))} files) — skipping"
        )
    else:
        chunks = chunk_book(book_path, chunks_dir, max_tokens, encoding_model)
        if not chunks:
            print("   ❌ No chunks generated!")
            return False

    # ─── Step 2: Distill ────────────────────────────────────
    print(f"\n{'─' * 40}")
    print("STEP 2/4: DISTILLING")
    print(f"{'─' * 40}")

    distill_prompt = load_distill_prompt(Path("distill_chunk_prompt.md"))
    newly_distilled = distill_book(chunks_dir, distilled_dir, config, distill_prompt)

    # ─── Step 3: Synthesize ─────────────────────────────────
    print(f"\n{'─' * 40}")
    print("STEP 3/4: SYNTHESIZING")
    print(f"{'─' * 40}")

    final_prompt = load_synth_prompt(Path("distill_final_prompt.md"))
    stats = synthesize_book(
        distilled_dir,
        synthesis_dir,
        book_dir,
        config,
        final_prompt,
        do_final,
    )

    # ─── Step 4: HTML Export ─────────────────────────────────
    if do_html:
        print(f"\n{'─' * 40}")
        print("STEP 4/5: HTML EXPORT")
        print(f"{'─' * 40}")
        export_html(book_dir, book_name, do_final)
    else:
        print(f"\n{'─' * 40}")
        print("STEP 4/5: HTML EXPORT (skipped)")
        print(f"{'─' * 40}")

    # ─── Step 5: EPUB Export ─────────────────────────────────
    if do_epub:
        print(f"\n{'─' * 40}")
        print("STEP 5/5: EPUB EXPORT")
        print(f"{'─' * 40}")
        export_epub(book_dir, book_name, do_final)
    else:
        print(f"\n{'─' * 40}")
        print("STEP 5/5: EPUB EXPORT (skipped)")
        print(f"{'─' * 40}")

    # Summary
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
    """Convert EPUB to markdown using pandoc or ebooklib."""
    md_path = book_dir / f"{epub_path.stem}.md"

    # Check if already converted
    if md_path.exists():
        print(f"   ✅ Already converted: {md_path.name}")
        return md_path

    # Try pandoc first
    import subprocess

    try:
        print(f"   📕 Converting EPUB → Markdown (pandoc)...")
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

    # Fallback: ebooklib
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup

        print(f"   📕 Converting EPUB → Markdown (ebooklib)...")
        book = epub.read_epoc(str(epub_path))
        # ... (basic conversion)
        print(f"   ⚠️  ebooklib conversion not yet implemented, use pandoc")
    except ImportError:
        pass

    print(
        f"   ❌ Could not convert EPUB. Install pandoc: https://pandoc.org/installing.html"
    )
    return None


def _convert_pdf(pdf_path: Path, book_dir: Path) -> Path | None:
    """Convert PDF to markdown using pypdf or pandoc."""
    md_path = book_dir / f"{pdf_path.stem}.md"

    # Check if already converted
    if md_path.exists():
        print(f"   ✅ Already converted: {md_path.name}")
        return md_path

    # Try pypdf first (faster, no external dependencies)
    try:
        print(f"   📕 Converting PDF → Markdown (pypdf)...")
        book_dir.mkdir(parents=True, exist_ok=True)

        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        text_content = []

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                # Add page separator for multi-page PDFs
                if i > 0:
                    text_content.append(f"\n\n---\n\n")
                text_content.append(page_text)

        if text_content:
            md_content = "".join(text_content)
            md_path.write_text(md_content, encoding="utf-8")
            print(f"   ✅ Converted: {md_path.name} ({md_path.stat().st_size:,} bytes)")
            return md_path
        else:
            print(f"   ⚠️  No text extracted from PDF")
    except ImportError:
        print(f"   ⚠️  pypdf not installed, trying pandoc...")
    except Exception as e:
        print(f"   ⚠️  pypdf failed: {e}")

    # Fallback: pandoc
    import subprocess

    try:
        print(f"   📕 Converting PDF → Markdown (pandoc)...")
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

    print(
        f"   ❌ Could not convert PDF. Install pypdf or pandoc: https://pypdf.readthedocs.io/"
    )
    return None


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  📚 BookConvert — Intellectual Distillation Pipeline     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check for config
    if not CONFIG_PATH.exists():
        print(f"\n⚠️  No {CONFIG_PATH} found — using defaults")
        print("   Create config.yaml to customize LLM settings")

    config = load_config()

    # Check for prompt files
    for prompt_file in [
        "distill_chunk_prompt.md",
        "distill_final_prompt.md",
    ]:
        if not Path(prompt_file).exists():
            print(f"\n❌ Missing: {prompt_file}")
            print(
                "   This file is required. It should be in the same directory as process.py"
            )
            sys.exit(1)

    # Find books
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Check for specific book argument
    specific_books = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]

    if specific_books:
        books = sorted(specific_books, key=lambda p: p.name.lower())
    else:
        books = find_books(INPUT_DIR)

    if not books:
        print(f"\n📂 No books found in {INPUT_DIR}/")
        print(f"   Drop .md or .epub files into {INPUT_DIR}/ and run again")
        sys.exit(0)

    print(f"\n📚 Found {len(books)} book(s) to process")

    # Process each book
    success = 0
    failed = 0
    for book_path in books:
        if not book_path.exists():
            print(f"\n❌ Not found: {book_path}")
            failed += 1
            continue

        try:
            if process_book(book_path, config):
                success += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print("\n\n⏸️  Interrupted! Progress is saved — run again to resume.")
            sys.exit(130)
        except Exception as e:
            print(f"\n❌ Error processing {book_path.name}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    # Final summary
    print(f"\n{'═' * 60}")
    print(f"🏁 ALL DONE")
    print(f"   ✅ Success: {success}")
    if failed:
        print(f"   ❌ Failed:  {failed}")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
