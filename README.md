# Rixie

> Too long; did Rixie.

<img src="assets/rixie.jpg" alt="Rixie" width="100%">

**Throw books in. Get distilled knowledge out.**

Rixie is an LLM-powered book distiller. Feed it a book (EPUB, PDF, Markdown, or plain text), and it extracts only the *functional* knowledge — mental models, actionable heuristics, bullshit detectors, and the one seed principle that rebuilds the whole argument.

The output isn't a summary. It's a **cognitive upgrade** — what the book makes you *capable of*, not just what it said.

---

## Editions

Rixie comes in two pipelines. V2 is the future. V1 is the stable legacy.

| | V1 (Legacy) | V2 (Progressive) |
|---|---|---|
| **Status** | Stable, frozen | Active development |
| **Pipeline** | Chunk → Distill → Synthesize → Export | Ingest → Cartography → Summarize → Overview → Render |
| **Output levels** | Chunks, Groups, Final | Block mini-summaries, Chapter summaries (short/detailed), Abstract |
| **Export** | HTML, EPUB, Audiobook (MP3) | HTML, EPUB, Podcast (short + long MP3) |
| **Resumability** | Step-level | Block-level checkpoints |
| **Prompt files** | 2 prompts | 6 per-stage prompts |
| **LLM SDK** | LiteLLM | Direct OpenAI SDK |
| **Best for** | Stable, well-tested, classic 3-level output | Chapter-level structure, audio podcasts, fine-grained control |

---

## Quickstart

### 1. Clone & Install

```bash
git clone <repo-url> Rixie
cd Rixie
uv sync
```

That's it. `uv` handles Python version (3.12), dependencies, and the virtual environment. No manual setup needed.

### 2. Configure Your LLM

Edit `config.yaml` — this is the only file you need to touch:

```yaml
llm:
  base_url: "http://localhost:58080/v1"  # OpenAI-compatible endpoint
  api_key: "local"                       # API key (use "local" for no auth)
  model: "gpt-4o-mini"                   # Model name
  temperature: 0.3                       # Creativity (0=deterministic, 1=chaos)
```

Point `base_url` and `model` at whatever LLM you're running — local (Ollama, LM Studio, vLLM) or remote (OpenAI, etc.). V2 has its own extended configuration section — see [V2 Configuration](#v2-configuration).

### 3. Drop a Book In

Put your book in the `input/` folder:

```bash
cp my_book.epub input/
# or .md, .txt, .pdf
```

Supported formats: `.md`, `.txt`, `.epub` (requires [pandoc](https://pandoc.org/installing.html)), `.pdf` (uses pypdf, no external dependencies).

### 4a. Run V2 Pipeline (Recommended)

```bash
uv run rixie v2 input/my_book.epub
```

This runs the full V2 pipeline: ingest, precise chunking, mini-summaries, chapter grouping, chapter summaries, abstract, HTML render, and EPUB export. It's fully resumable — kill it anytime with Ctrl+C and re-run, it picks up where it left off.

**Output lands in:** `output/v2/my-book-slug/`

### 4b. Run V1 Pipeline (Legacy)

```bash
uv run rixie v1 input/my_book.epub
```

Runs the classic three-level distillation pipeline. Stable and well-tested.

**Output lands in:** `output/v1/My_Book/`

### 5. Find Your Output

```
output/
├── v1/My_Book/                       ← V1 pipeline output
│   ├── chunks/                       ← Smart chunks (respects chapters)
│   ├── distilled/                    ← Level 1: Per-chunk distillations
│   ├── synthesis/                    ← Level 2: Group distillations
│   ├── final.md                      ← Level 3: Readable article
│   ├── My_Book.html                  ← HTML viewer
│   └── My_Book.epub                  ← EPUB export
│
└── v2/my-book-slug/                  ← V2 pipeline output
    ├── book.yaml                     ← Full artifact (all stages)
    ├── source.md                     ← Normalized source text
    ├── my-book-slug.html             ← Scrollytelling HTML viewer
    └── my-book-slug.epub             ← Progressive-disclosure EPUB
```

Open the `.html` file in a browser, the `.epub` in your e-reader, or generate an audiobook/podcast — see [Audiobook & Podcast](#audiobook--podcast).

---

## V2 Pipeline (Recommended)

The future of Rixie. V2 is a progressive, checkpointed pipeline with 6 stages, each building on the last.

### Pipeline Overview

```
source.epub
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 0: INGESTION                                    │
│ Converts EPUB/PDF/MD/TXT → normalized source.md       │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 1: CARTOGRAPHY — PRECISE CHUNKING              │
│ LLM identifies semantic boundaries (no mid-thought   │
│ splits). Falls back to mechanical token-splitting if │
│ the LLM returns no boundaries.                       │
│ Output: blocks with char offsets                     │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 2: MINI-SUMMARIES                              │
│ Each block gets a one-sentence summary + useful/not   │
│ useful classification. Non-useful blocks excluded.   │
│ SEQUENTIAL — one LLM call per block.                 │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 3: CHAPTER GROUPING (Cartographer)              │
│ LLM groups useful blocks into chapters via multi-turn │
│ validation (up to 6 rounds). Gaps/overlaps detected  │
│ and fed back for correction.                          │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 4: CHAPTER SUMMARIZATION                        │
│ Each chapter gets TWO summaries:                      │
│  • SHORT (concise overview)                          │
│  • DETAILED (in-depth extraction)                    │
│ SEQUENTIAL — checkpointed every N%.                  │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 5: OVERVIEW SYNTHESIS                           │
│ All short summaries compressed into one ultra-dense   │
│ abstract. The "one paragraph to rule them all."       │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Stage 6: RENDER + EXPORT                              │
│  • HTML: Scrollytelling template with full data       │
│  • EPUB: Progressive-disclosure with expandable       │
│    <details> sections                                 │
│  • Podcast: 2 audio versions (short + long)           │
└──────────────────────────────────────────────────────┘
    │
    ▼
    output/v2/{slug}/
```

### Key Capabilities

**Precise Chunking (Step 0):** Instead of mechanical token-splitting, V2 sends overlapping token windows to the LLM as line-numbered text. The LLM identifies natural semantic boundaries (paragraph breaks, topic shifts, section transitions). The result: blocks that never split mid-thought.

**Multi-Turn Cartographer:** Chapter grouping happens in a feedback loop. The LLM proposes chapter boundaries, validation checks for gaps (uncovered blocks) and overlaps (blocks in multiple chapters), and errors are fed back for up to 6 correction rounds. This produces clean, consistent chapter maps.

**Checkpoint Resumability:** Every stage saves progress at configurable intervals (default: every 5% of work completed). Crashes and Ctrl+C cost at most one checkpoint interval of redundant LLM calls. Resume by re-running the exact same command.

**Per-Profile LLM Settings:** Each pipeline stage can use a different model, temperature, or thinking mode. See [V2 Configuration](#v2-configuration).

### CLI Reference

```bash
# Run full V2 pipeline on a single book
uv run rixie v2 input/my_book.epub

# Run V2 on all books in input/
uv run rixie v2

# Smoke-test: process only first 10 blocks
uv run rixie v2 input/my_book.epub --max-blocks 10

# Show all V2 options
uv run rixie v2 --help
```

---

## V1 Pipeline (Legacy)

The original Rixie pipeline. Stable, well-tested, and now maintained in maintenance mode under `v1/`.

### Three Levels of Distillation

Every book produces three layers of output, from deep to digestible:

| Level | What | Where | Read Time |
|-------|------|-------|-----------|
| **1 — Chunks** | Raw per-chapter distillations. Full detail, every mental model extracted. | `distilled/*.md` | ~20+ min |
| **2 — Groups** | Thematic clusters. Deduplicated, connected, cross-chapter patterns emerge. | `synthesis/group_*.md` | ~10 min |
| **3 — Final** | One readable article. Plain language, analogies, flowing prose. The "vibe check." | `final.md` | ~2 min |

Start with the Final for the big picture. Go to Groups for depth. Dive into Chunks when you want *everything*.

### Pipeline Stages

#### Stage 1: Chunking
The book is split into chunks that respect natural boundaries (chapters, sections) while staying within a token limit (default: 8k tokens).

#### Stage 2: Per-Chunk Distillation → Level 1 (Chunks)
Each chunk goes through the LLM individually. It extracts:
- **Receptors** — new mental models and lenses
- **Operations** — actionable heuristics and procedures
- **Immune Responses** — bullshit detection patterns
- **Generator** — the one principle that rebuilds the whole book

Anecdotes and examples get stripped. Only functional knowledge survives.

#### Stage 3: Synthesis → Level 2 (Groups) + Level 3 (Final)

**Group Synthesis** — Chunks pack into ~8k token groups and merge. Deduplicated, connected, elevated. Cross-chunk patterns become visible.

**Final Synthesis** — All groups get rewritten into a single, readable article. Plain language, analogies, flowing prose. Prioritizes connection and readability over density. The "explain it to a friend" version.

### CLI Reference

```bash
# Process all books in input/
uv run rixie v1

# Process a specific book
uv run rixie v1 input/my_book.epub

# Skip final merge step (groups only)
uv run rixie v1 input/my_book.epub --no-final

# Skip HTML export
uv run rixie v1 input/my_book.epub --no-html

# Skip EPUB export
uv run rixie v1 input/my_book.epub --no-epub

# Skip both
uv run rixie v1 input/my_book.epub --no-html --no-epub

# Show all V1 options
uv run rixie v1 --help
```

### V1 Prompt Files

| Prompt | File | Controls |
|--------|------|----------|
| Chunk distillation | `v1/distill_chunk_prompt.md` | How each chunk is distilled |
| Final synthesis | `v1/distill_final_prompt.md` | How the final article is written |

Edit these to change what kind of knowledge gets extracted. The defaults focus on mental models, operations, immune responses, and seed principles.

---

## Audiobook & Podcast

Both pipelines support audio output. V1 uses the standalone `audiobook.py` for distillation output. V2 has a dedicated podcast generator that produces two lengths.

### V1 Audiobook

Converts V1 distillation output (groups + final) to MP3 using [edge-tts](https://github.com/rany2/edge-tts) (Microsoft neural voices, 400+ options).

```bash
# Interactive menu — pick book, content, voice
uv run rixie audiobook

# Skip book selection if only one book
uv run rixie audiobook --book "Thinking"

# Pick voice directly
uv run rixie audiobook --voice en-US-GuyNeural

# Adjust speed
uv run rixie audiobook --rate "+15%"

# Show all options
uv run rixie audiobook --help
```

**What you get:**

| File | Content |
|------|---------|
| `audiobook/groups.mp3` | All groups combined into one track |
| `audiobook/final.mp3` | Final synthesis as one track |

If ffmpeg is installed, groups are generated segment-by-segment then merged for better audio quality.

### V2 Podcast

Generates two MP3 versions from a V2 workspace:

- **Short:** Title → Abstract → short summaries (quick listen)
- **Long:** Title → Abstract → detailed summaries (deep dive)

```bash
# Generate both short and long podcast
uv run python -m v2.podcast output/v2/my-book-slug

# Choose voice and speed
uv run python -m v2.podcast output/v2/my-book-slug --voice en-US-GuyNeural --rate "+10%"

# Only short version
uv run python -m v2.podcast output/v2/my-book-slug --mode short

# List available voices
uv run python -m v2.podcast output/v2/my-book-slug --list-voices
```

**Output:** `{slug}-podcast-short.mp3` and `{slug}-podcast-long.mp3`

### Available Voices

| Key | Voice |
|-----|-------|
| `aria` | US Aria (Female, warm) |
| `jenny` | US Jenny (Female, friendly) |
| `guy` | US Guy (Male, natural) |
| `eric` | US Eric (Male, calm) |
| `sonia` | GB Sonia (Female, British) |
| `ryan` | GB Ryan (Male, British) |

Or use any [edge-tts voice name](https://github.com/rany2/edge-tts#supported-voices) directly.

---

## Configuration

### LLM Settings

The `llm` section in `config.yaml` serves as the base configuration for V1. V2 has its own extended section (see below).

```yaml
llm:
  base_url: "http://localhost:58080/v1"  # OpenAI-compatible endpoint
  api_key: "local"                       # API key (use "local" for no auth)
  model: "gpt-4o-mini"                   # Model name
  temperature: 0.3                       # Creativity (0=deterministic, 1=chaos)
  request_timeout_seconds: 300           # Per-call timeout
```

### V1 Chunking

```yaml
chunking:
  max_tokens: 8000             # Max tokens per chunk (tiktoken)
  encoding_model: "gpt-4o-mini"    # Which tokenizer to use
```

### V1 Synthesis

```yaml
synthesis:
  temperature: 0.4           # Slightly higher for creative synthesis
  context_window: 64000      # Your LLM's context window size
  prompt_overhead: 2000      # Reserved for system prompt
  response_reserve: 8000     # Reserved for LLM response
  group_target_tokens: 8000  # Tokens per group (same as chunking max_tokens)
  final_chunk_size: 40000    # Target tokens per final synthesis pass
```

### V2 Configuration

V2 has a **layered configuration** system — profiles inherit from defaults and can override specific fields:

```yaml
v2:
  defaults:
    base_url: "http://localhost:58080/v1"   # Shared endpoint
    api_key: "local"                         # Shared key
    model: "gpt-4o-mini"                     # Shared default model
    temperature: 0.2                         # Shared default temperature
    request_timeout_seconds: 300             # Per-call timeout
    thinking: true                           # Enable reasoning effort

  profiles:
    mini_summary:                            # Block mini-summaries
      prompt_file: "prompt_block_mini_summary.md"
      temperature: 0.1
      thinking: false

    cartography:                             # Chapter grouping
      prompt_file: "prompt_cartographer_map.md"
      thinking: true

    chapter_short:                           # Short chapter summaries
      prompt_file: "prompt_chapter_short.md"
      temperature: 0.25
      thinking: true

    chapter_long:                            # Detailed chapter summaries
      prompt_file: "prompt_chapter_detailed.md"
      temperature: 0.25
      thinking: true
```

Each profile can independently override `model`, `temperature`, `base_url`, `api_key`, `request_timeout_seconds`, and `thinking`. Unset fields fall through to `defaults`.

#### V2 Blocking (Precise Chunking)

Controls how the source text is split into blocks:

```yaml
v2:
  blocking:
    encoding_model: "gpt-4o-mini"     # Tokenizer for synthetic page splitting
    target_tokens: 4096                # Target synthetic-page size
    min_tokens: 3884                   # Minimum before forcing a split
    max_tokens: 4396                   # Hard cap before forcing a split
    window_tokens: 8000                # Token budget per LLM chunking window
    max_boundaries_per_window: 16      # Max LLM boundary returns per window
    overlap_pct: 0.05                  # 5% overlap between windows

  execution:
    parallel_calls: 1                  # Sequential (set >1 for fast remote models)
    checkpoint_pct: 5.0                # Save progress every 5% of work
```

---

## Output Formats

### HTML Viewer

**V1:** Dark-themed, tabbed interface with three sections (Short Version, Groups, All Chunks). Features lazy-loaded markdown rendering and a theme switcher (White, Paper, Dusk, OLED, Dimmed, Midnight).

**V2:** Scrollytelling template with full artifact data embedded inline. The template owns all HTML/CSS/JS — Python just injects the JSON data.

### EPUB Export

**V1:** Standard EPUB3 format with proper navigation. Linear structure with three sections. Works in any e-reader.

**V2:** Progressive-disclosure EPUB3 with `<details>` expandable sections. Title page → Abstract → Chapter summaries (short visible, detailed expandable) → End page. Beautiful typography with thematic styling.

### Audiobook / Podcast

**V1:** Per-book MP3 tracks for groups and final synthesis via edge-tts.

**V2:** Dual-length podcast MP3s — short version (abstract + short summaries) for quick listening, long version (abstract + detailed summaries) for deep dives.

---

## Supported Input

| Format | Method |
|--------|--------|
| `.md` | Direct processing |
| `.epub` | Auto-converts via pandoc (must be installed) |
| `.pdf` | Auto-converts via pypdf (no external dependencies) |
| `.txt` | Direct processing |

For EPUB support, install [pandoc](https://pandoc.org/installing.html).
For audio merging, install [ffmpeg](https://ffmpeg.org/download.html).

---

## Project Structure

```
Rixie/
├── input/                              ← Drop books here
├── output/
│   ├── v1/{book_name}/                 ← V1 pipeline output
│   └── v2/{book_slug}/                 ← V2 pipeline output
│
├── v1/                                 ← Legacy V1 pipeline
│   ├── __init__.py                     ← V1 package, exports REPO_ROOT
│   ├── _paths.py                       ← Asset/config path resolution
│   ├── process.py                      ← Pipeline orchestrator & CLI
│   ├── chunker.py                      ← Smart chapter-respecting chunking
│   ├── distiller.py                    ← LLM distillation per chunk
│   ├── synthesizer.py                  ← Group + final synthesis
│   ├── export_html.py                  ← HTML viewer export
│   ├── export_epub.py                  ← EPUB export
│   ├── distill_chunk_prompt.md         ← Chunk distillation prompt
│   └── distill_final_prompt.md         ← Final synthesis prompt
│
├── v2/                                 ← Progressive V2 pipeline
│   ├── __init__.py                     ← V2 package, version
│   ├── process.py                      ← CLI + workspace bootstrap
│   ├── pipeline.py                     ← OpenAI SDK completion helpers
│   ├── schema.py                       ← Pydantic artifact models
│   ├── config.py                       ← V2 config loader with deep merge
│   ├── ingest.py                       ← Format detection & conversion
│   ├── blocker.py                      ← Mechanical block splitting
│   ├── cartographer.py                 ← LLM chunking + chapter grouping
│   ├── summarizer.py                   ← Chapter summaries + abstract
│   ├── checkpoint.py                   ← Throttled checkpoint saves
│   ├── renderer.py                     ← HTML renderer (data injection)
│   ├── export_epub.py                  ← EPUB3 progressive-disclosure export
│   ├── podcast.py                      ← Dual-length audio podcast generator
│   ├── prompts.py                      ← Prompt file loader
│   ├── template.html                   ← Scrollytelling HTML template
│   ├── prompt_block_mini_summary.md
│   ├── prompt_cartographer_map.md
│   ├── prompt_chapter_short.md
│   ├── prompt_chapter_detailed.md
│   ├── prompt_precise_chunk.md
│   └── prompt_ultra_dense.md
│
├── main.py                             ← CLI entry point (rixie)
├── audiobook.py                        ← V1 audiobook generator (edge-tts)
├── copy_to_reading_list.py             ← HTML export organizer
├── config.yaml                         ← Shared pipeline configuration
├── pyproject.toml                      ← Project metadata & scripts
├── uv.lock                             ← Dependency lock file
├── .python-version                     ← Python version pin (3.12)
├── .editorconfig                       ← Editor consistency
├── Makefile                            ← Common commands
├── .gitignore
│
├── assets/
│   └── rixie.jpg                       ← README hero image
│
├── skills/
│   └── rixie-book-distillation/        ← Agent skill for AI coding tools
│       └── SKILL.md
│
├── private/                            ← Personal notes (gitignored)
├── memory/                             ← Agent memory (gitignored)
└── LICENSE                             ← MIT
```

---

## Dependencies

All managed by `uv` — auto-installed with `uv sync`:

| Package | Purpose |
|---------|---------|
| `openai` | OpenAI SDK (V2 pipeline) |
| `litellm` | LiteLLM SDK (V1 pipeline) |
| `pyyaml` | Config file parsing |
| `tiktoken` | Token counting |
| `pydantic` | Data models (V2 schema) |
| `edge-tts` | Text-to-speech (audiobook + podcast) |
| `ebooklib` | EPUB generation |
| `markdown` | Markdown-to-HTML conversion |
| `pypdf` | PDF text extraction |

---

## Commands Cheatsheet

| Action | Command |
|--------|---------|
| Install | `uv sync` |
| V1 pipeline (all books) | `uv run rixie v1` |
| V1 pipeline (one book) | `uv run rixie v1 input/book.epub` |
| V2 pipeline (all books) | `uv run rixie v2` |
| V2 pipeline (one book) | `uv run rixie v2 input/book.epub` |
| V2 smoke test (10 blocks) | `uv run rixie v2 input/book.epub --max-blocks 10` |
| Audiobook (V1) | `uv run rixie audiobook` |
| Podcast (V2) | `uv run python -m v2.podcast output/v2/slug` |
| Reading list | `uv run rixie reading-list` |
| Help | `uv run rixie help` |

### Makefile Alternatives

```bash
make install         # uv sync
make v1              # Run V1 on all books
make v2              # Run V2 on all books
make v2-book B=file.epub   # V2 on a specific book
make audiobook       # Interactive audiobook
make reading-list    # Copy HTMLs to reading list
make lint            # ruff check
make format          # ruff format
make clean           # Remove caches
make help            # Show all targets
```

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 lirrensi.
