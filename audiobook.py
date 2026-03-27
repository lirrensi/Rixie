#!/usr/bin/env python3
"""
BookConvert — Audiobook Generator

Converts distillation outputs to audio using edge-tts (Microsoft neural voices).

Usage:
    uv run python audiobook.py                          # Interactive menu
    uv run python audiobook.py --book "Thinking_Fast"   # Skip book selection
    uv run python audiobook.py --voice en-US-GuyNeural  # Pick voice
    uv run python audiobook.py --rate "+15%"            # Speed up

Output:
    output/{book_name}/audiobook/
        ├── groups.mp3      # All groups combined into one track
        └── final.mp3       # Final synthesis as one track
"""

import sys
import re
import asyncio
import tempfile
import subprocess
from pathlib import Path

import edge_tts


OUTPUT_DIR = Path("output")

# ─── Recommended voices ──────────────────────────────────────────
VOICES = {
    "aria": {"name": "en-US-AriaNeural", "label": "🇺🇸 Aria (Female, warm)"},
    "jenny": {"name": "en-US-JennyNeural", "label": "🇺🇸 Jenny (Female, friendly)"},
    "guy": {"name": "en-US-GuyNeural", "label": "🇺🇸 Guy (Male, natural)"},
    "eric": {"name": "en-US-EricNeural", "label": "🇺🇸 Eric (Male, calm)"},
    "sonia": {"name": "en-GB-SoniaNeural", "label": "🇬🇧 Sonia (Female, British)"},
    "ryan": {"name": "en-GB-RyanNeural", "label": "🇬🇧 Ryan (Male, British)"},
}


# ─── Markdown → Plain text ───────────────────────────────────────
def md_to_speech_text(md: str) -> str:
    """Strip markdown formatting for clean TTS reading."""
    text = md

    # Remove YAML frontmatter
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)

    # Code blocks → skip content, keep a note
    text = re.sub(r"```[\s\S]*?```", "[code block omitted]", text, flags=re.DOTALL)

    # Headings: keep the text, add pause
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1.", text, flags=re.MULTILINE)

    # Bold/italic markers
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)

    # Inline code
    text = re.sub(r"`(.+?)`", r"\1", text)

    # Links: keep text, drop URL
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)

    # Images
    text = re.sub(r"!\[.*?\]\(.+?\)", "[image]", text)

    # Tables: convert to readable format
    lines = text.split("\n")
    clean_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
            # Skip separator rows
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue
            # Convert table row to comma-separated
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            cells = [c for c in cells if c and not re.match(r"^[\-:]+$", c)]
            if cells:
                clean_lines.append(". ".join(cells) + ".")
        else:
            if in_table:
                in_table = False
                clean_lines.append("")
            clean_lines.append(line)
    text = "\n".join(clean_lines)

    # Horizontal rules → pause
    text = re.sub(r"^[-*_]{3,}$", "\n---\n", text, flags=re.MULTILINE)

    # List markers
    text = re.sub(r"^[\s]*[-*+]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Blockquotes
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)

    return text.strip()


# ─── Audio generation ────────────────────────────────────────────
async def text_to_mp3(text: str, output_path: Path, voice: str, rate: str):
    """Convert text to MP3 using edge-tts."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))


def has_ffmpeg() -> bool:
    """Check if ffmpeg is available for audio merging."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


async def merge_mp3s(mp3_paths: list[Path], output_path: Path):
    """Merge multiple MP3s into one using ffmpeg."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in mp3_paths:
            f.write(f"file '{p.absolute()}'\n")
        concat_file = f.name

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-c",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"   ⚠️  ffmpeg merge failed: {proc.stderr[:200]}")
            return False
        return True
    finally:
        Path(concat_file).unlink(missing_ok=True)


# ─── Scan for available content ──────────────────────────────────
def find_books() -> list[dict]:
    """Find all books with distillation output."""
    books = []
    if not OUTPUT_DIR.exists():
        return books

    for book_dir in sorted(OUTPUT_DIR.iterdir()):
        if not book_dir.is_dir():
            continue

        info = {
            "name": book_dir.name,
            "dir": book_dir,
            "has_final": (book_dir / "final.md").exists(),
            "has_combined": (book_dir / "synthesis" / "combined.md").exists()
            if (book_dir / "synthesis").exists()
            else False,
            "has_distilled": False,
        }
        info["has_distilled"] = (book_dir / "distilled").exists() and any(
            (book_dir / "distilled").glob("*_distilled.md")
        )

        if info["has_final"] or info["has_combined"] or info["has_distilled"]:
            books.append(info)

    return books


# ─── Interactive menu ────────────────────────────────────────────
def pick_book(books: list[dict]) -> dict | None:
    """Let user pick a book from available ones."""
    print("\n📚 Available books:\n")
    for i, book in enumerate(books, 1):
        parts = []
        if book["has_final"]:
            parts.append("final")
        if book["has_combined"]:
            parts.append("combined")
        status = ", ".join(parts) if parts else "distilled chunks only"
        print(f"   {i}. {book['name']}")
        print(f"      └─ {status}")

    print()
    choice = input("Pick a book (number) or 'q' to quit: ").strip()
    if choice.lower() == "q":
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(books):
            return books[idx]
    except ValueError:
        pass

    print("❌ Invalid choice")
    return None


def pick_content(book: dict) -> list[str]:
    """Let user pick what to convert to audio."""
    print(f"\n📖 {book['name']}\n")

    options = []
    if book["has_combined"]:
        options.append(("combined", "🎧 Combined knowledge (1 track)"))
    if book["has_final"]:
        options.append(("final", "📄 Final synthesis (1 track)"))
    if book["has_distilled"] and not book["has_combined"] and not book["has_final"]:
        options.append(("distilled", "📝 Distilled chunks (all → 1 track)"))

    for i, (_, label) in enumerate(options, 1):
        print(f"   {i}. {label}")
    print(f"   a. All of the above")

    print()
    choice = input("Pick content (number, 'a' for all) or 'q' to quit: ").strip()
    if choice.lower() == "q":
        return []
    if choice.lower() == "a":
        return [key for key, _ in options]

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return [options[idx][0]]
    except ValueError:
        pass

    print("❌ Invalid choice")
    return []


def pick_voice() -> tuple[str, str]:
    """Let user pick a voice. Returns (voice_name, rate)."""
    print("\n🎙️  Voice:\n")
    voice_keys = list(VOICES.keys())
    for i, key in enumerate(voice_keys, 1):
        print(f"   {i}. {VOICES[key]['label']}")

    print()
    choice = input("Pick voice (number, default=1) or 'q' to quit: ").strip()
    if choice.lower() == "q":
        return ("", "")

    try:
        idx = int(choice) - 1 if choice else 0
        if 0 <= idx < len(voice_keys):
            voice = VOICES[voice_keys[idx]]["name"]
        else:
            voice = VOICES["aria"]["name"]
    except ValueError:
        voice = VOICES["aria"]["name"]

    rate = input("Speed (e.g. +10%, -20%, default=+0%): ").strip() or "+0%"

    return (voice, rate)


# ─── Main processing ─────────────────────────────────────────────
async def generate_audiobook(
    book: dict, content_types: list[str], voice: str, rate: str
):
    """Generate audiobook files for the selected content."""
    audiobook_dir = book["dir"] / "audiobook"
    audiobook_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_available = has_ffmpeg()

    for content_type in content_types:
        print(f"\n{'─' * 40}")

        if content_type == "combined":
            print("🎧 Generating: Combined knowledge track")
            combined_path = book["dir"] / "synthesis" / "combined.md"
            if not combined_path.exists():
                print("   ⚠️  No combined.md found")
                continue

            md = combined_path.read_text(encoding="utf-8")
            text = md_to_speech_text(md)
            word_count = len(text.split())
            print(f"   📝 ~{word_count:,} words")

            output_path = audiobook_dir / "combined.mp3"
            print(f"   🔄 Generating...", end="", flush=True)
            await text_to_mp3(text, output_path, voice, rate)
            size = output_path.stat().st_size
            print(f" ✅ {output_path.name} ({size:,} bytes)")

        elif content_type == "final":
            print("📄 Generating: Final synthesis track")
            md = (book["dir"] / "final.md").read_text(encoding="utf-8")
            text = md_to_speech_text(md)
            word_count = len(text.split())
            print(f"   📝 ~{word_count:,} words")

            output_path = audiobook_dir / "final.mp3"
            print(f"   🔄 Generating...", end="", flush=True)
            await text_to_mp3(text, output_path, voice, rate)
            size = output_path.stat().st_size
            print(f" ✅ {output_path.name} ({size:,} bytes)")

        elif content_type == "distilled":
            print("📝 Generating: Distilled chunks track")
            distilled_dir = book["dir"] / "distilled"
            files = sorted(distilled_dir.glob("*_distilled.md"))

            texts = []
            for f in files:
                md = f.read_text(encoding="utf-8")
                text = md_to_speech_text(md)
                if text.strip():
                    texts.append(text)

            if not texts:
                print("   ⚠️  No distilled content found")
                continue

            combined = "\n\n---\n\n".join(texts)
            word_count = len(combined.split())
            print(f"   📝 {len(texts)} chunks, ~{word_count:,} words")

            if ffmpeg_available and len(texts) > 1:
                temp_mp3s = []
                for i, text in enumerate(texts):
                    temp_path = audiobook_dir / f"_temp_chunk_{i:03d}.mp3"
                    print(
                        f"      [{i + 1}/{len(texts)}] Chunk {i:03d}...",
                        end="",
                        flush=True,
                    )
                    await text_to_mp3(text, temp_path, voice, rate)
                    print(f" ✅")
                    temp_mp3s.append(temp_path)

                output_path = audiobook_dir / "distilled.mp3"
                print(f"   🔗 Merging...", end="", flush=True)
                await merge_mp3s(temp_mp3s, output_path)
                print(f" ✅ {output_path.name}")

                for tp in temp_mp3s:
                    tp.unlink(missing_ok=True)
            else:
                output_path = audiobook_dir / "distilled.mp3"
                print(f"   🔄 Generating...", end="", flush=True)
                await text_to_mp3(combined, output_path, voice, rate)
                size = output_path.stat().st_size
                print(f" ✅ {output_path.name} ({size:,} bytes)")


# ─── Entry point ─────────────────────────────────────────────────
async def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  🎧 BookConvert — Audiobook Generator                   ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Parse optional flags
    book_filter = None
    voice_override = None
    rate_override = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--book" and i + 1 < len(args):
            book_filter = args[i + 1]
            i += 2
        elif args[i] == "--voice" and i + 1 < len(args):
            voice_override = args[i + 1]
            i += 2
        elif args[i] == "--rate" and i + 1 < len(args):
            rate_override = args[i + 1]
            i += 2
        elif args[i] == "--help":
            print(
                "\nUsage: uv run python audiobook.py [--book NAME] [--voice VOICE] [--rate +10%]"
            )
            print("\nFlags:")
            print("  --book NAME    Filter to book containing NAME")
            print("  --voice VOICE  Use specific edge-tts voice name")
            print("  --rate +/-X%   Speed adjustment (e.g. +15%, -20%)")
            return
        else:
            i += 1

    # Find books
    books = find_books()
    if not books:
        print("\n📂 No completed distillations found in output/")
        print("   Run `uv run python process.py` first to distill some books")
        return

    # Filter by name if specified
    if book_filter:
        filtered = [b for b in books if book_filter.lower() in b["name"].lower()]
        if not filtered:
            print(f"\n❌ No book matching '{book_filter}'")
            return
        books = filtered

    # If only one book and filter specified, auto-select
    if len(books) == 1 and book_filter:
        book = books[0]
        print(f"\n📖 Auto-selected: {book['name']}")
    else:
        book = pick_book(books)
        if not book:
            return

    # Pick content
    content_types = pick_content(book)
    if not content_types:
        return

    # Pick voice
    if voice_override:
        voice = voice_override
        rate = rate_override or "+0%"
        print(f"\n🎙️  Voice: {voice} (rate: {rate})")
    else:
        voice, rate = pick_voice()
        if not voice:
            return

    # Generate
    print(f"\n{'═' * 50}")
    print(f"🎧 Generating audiobook for: {book['name']}")
    print(f"   Voice: {voice}")
    print(f"   Rate:  {rate}")
    print(f"{'═' * 50}")

    await generate_audiobook(book, content_types, voice, rate)

    print(f"\n{'═' * 50}")
    print(f"✅ Done! Files in: {book['dir'] / 'audiobook'}/")
    print(f"{'═' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
