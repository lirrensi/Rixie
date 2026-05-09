# Getting Started with Rixie

> The complete guide to installing, configuring, and running Rixie.

---

## Quick Reference

| I want to... | Jump to |
|---|---|
| Install and run my first book | [Installation](#installation) → [Configuration](#configuration) → [Running the Pipeline](#running-the-pipeline) |
| Pick an LLM (local or cloud) | [Choosing Your LLM Backend](#choosing-your-llm-backend) |
| Understand every config option | [Configuration](#configuration) |
| Change how the output *sounds* | [Prompt Files](#prompt-files) — only Personality and Goal |
| Run V2 on a book | [V2 Pipeline](#v2-pipeline-recommended) |
| Run V1 (legacy) | [V1 Pipeline](#v1-pipeline-legacy) |
| Generate audiobook / podcast | [Audio Output](#audio-output) |
| See all commands at a glance | [Commands Cheatsheet](#commands-cheatsheet) |
| See the Makefile targets | [Makefile Reference](#makefile-reference) |
| Explore the codebase layout | [Project Structure](#project-structure) |

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Choosing Your LLM Backend](#choosing-your-llm-backend)
- [Configuration](#configuration)
- [Prompt Files](#prompt-files)
- [Running the Pipeline](#running-the-pipeline)
  - [V2 Pipeline (Recommended)](#v2-pipeline-recommended)
  - [V1 Pipeline (Legacy)](#v1-pipeline-legacy)
- [Audio Output](#audio-output)
  - [V1 Audiobook](#v1-audiobook)
  - [V2 Podcast](#v2-podcast)
- [Output Formats](#output-formats)
- [Commands Cheatsheet](#commands-cheatsheet)
- [Makefile Reference](#makefile-reference)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)
- [Supported Input Formats](#supported-input-formats)

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.12+** | Managed automatically by `uv` — see `.python-version` |
| **uv** | Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| **pandoc** | Required for EPUB input — [pandoc.org](https://pandoc.org/installing.html) |
| **ffmpeg** | Optional — enables segment-by-segment audio merging for better quality — [ffmpeg.org](https://ffmpeg.org/download.html) |

No global installation needed. Everything runs from the cloned directory.

---

## Installation

### 1. Clone

```bash
git clone <repo-url> Rixie
cd Rixie
```

### 2. Install dependencies

```bash
uv sync
```

This single command does everything:
- Reads `.python-version` and ensures Python 3.12 is available
- Creates a `.venv` virtual environment
- Installs all dependencies from `uv.lock`

**No manual setup. No global installs. No pip.**

---

## Choosing Your LLM Backend

Rixie works with any OpenAI-compatible endpoint. You have two options: run models locally (if you have a GPU) or use a cloud API.

But first, it helps to understand Rixie's two distinct LLM workloads:

### Two Types of Work

Rixie doesn't use the same model for everything. The pipeline splits into two very different kinds of work:

| Workload | Stages | Behavior | Model Needs |
|----------|--------|----------|-------------|
| **Cartography** | Precise chunking + chapter grouping | Lots of parallel calls, brute-force boundary detection. Many short prompts. | Small, fast, cheap. **4-8B range.** Prefer models **without** thinking/reasoning — it adds latency for no gain. |
| **Summarization** | Mini-summaries, chapter summaries, abstract | Fewer calls, longer context, quality-critical. | Bigger, smarter. **~30B range works surprisingly well.** Use thinking for long summaries, **disable thinking for mini-summaries** (short task, not worth the overhead). |

This is why V2's per-profile configuration exists — you can pair a tiny model for cartography and a powerful one for summaries.

### Option 1: Run Local (llama.cpp)

If you have a GPU, [**llama.cpp**](https://github.com/ggml-org/llama.cpp) is the quickest path to running local models. It serves an OpenAI-compatible endpoint out of the box.

```bash
# Quick start:
# 1. Download llama.cpp or use a pre-built binary
# 2. Download a GGUF model (see recommendations below)
# 3. Start the server:
./llama-server -m models/gemma-4-4b-it.Q4_K_M.gguf --port 8080

# Then in config.yaml:
#   base_url: "http://localhost:8080/v1"
#   api_key: "local"
```

### Option 2: OpenRouter (No GPU Required)

If you don't have a GPU, [OpenRouter](https://openrouter.ai/) gives you pay-per-token access to hundreds of models. It's the cheapest cloud option for running this kind of pipeline.

```yaml
# In config.yaml:
llm:
  base_url: "https://openrouter.ai/api/v1"
  api_key: "sk-or-v1-..."        # Your OpenRouter key
```

### Hardware-Guided Recommendations

| Your Hardware | Cartography (chunking) | Summarization | Notes |
|---|---|---|---|
| **No GPU / limited VRAM** | **Gemma 4 4B** or **Ministral 3 8B** | Same model, or swap to OpenRouter | Both fit in 12GB at Q4. Disable thinking for both roles. |
| **24 GB VRAM** | **Qwen 3.6 31B** | Same model | Disable thinking for cartography and mini-summaries (short tasks). Enable it for chapter summaries and abstract. |

### Configuring a Two-Model Setup

In `config.yaml`, wire up different models per pipeline stage using V2 profiles:

```yaml
v2:
  defaults:
    base_url: "http://localhost:8080/v1"    # Point at llama.cpp
    api_key: "local"
    model: "gpt-4o-mini"                    # Fallback

  profiles:
    mini_summary:                           # Fast bulk work
      temperature: 0.1
      thinking: false                       # Disable thinking for speed

    cartography:                            # Chunking + chapter grouping
      model: "gemma-4-4b"                  # Small, fast model
      thinking: false                       # No thinking needed here

    chapter_short:                          # Short summaries
      model: "qwen-3-31b"                  # Bigger model for quality
      thinking: true                        # Thinking helps

    chapter_long:                           # Detailed summaries
      model: "qwen-3-31b"                  # Same big model
      thinking: true                        # Definitely want thinking
```

> **Tip:** The thinking toggle (`thinking: true/false`) is critical. Cartography and mini-summaries benefit from speed over depth — keep thinking off. Chapter summaries and abstract benefit from reasoning — turn it on.

---

All configuration lives in **`config.yaml`** at the repo root. Open it in any editor.

### LLM Connection (used by V1, inherited by V2)

```yaml
llm:
  base_url: "http://localhost:58080/v1"   # Your OpenAI-compatible endpoint
  api_key: "local"                        # API key ("local" = no auth)
  model: "gpt-4o-mini"                    # Model name
  temperature: 0.3                        # 0.0 = deterministic, 1.0 = chaos
  request_timeout_seconds: 300            # Max seconds per LLM call
```

**Examples for common setups:**

| Setup | `base_url` | `api_key` |
|-------|-----------|-----------|
| Ollama (local) | `http://localhost:11434/v1` | `local` |
| LM Studio (local) | `http://localhost:1234/v1` | `local` |
| vLLM (local) | `http://localhost:8000/v1` | `local` |
| OpenAI | `https://api.openai.com/v1` | `<your-key>` |
| Any OpenAI-compatible proxy | `http://your-proxy:port/v1` | as required |

### V1 Chunking

Controls how books are split into chunks for distillation:

```yaml
chunking:
  max_tokens: 8000            # Target tokens per chunk
  encoding_model: "gpt-4o-mini"  # Tokenizer model
```

- `max_tokens`: Larger = fewer, richer chunks. Smaller = more granular, parallelizable.
- `encoding_model`: Must match a model available in `tiktoken`. Use the same model you're running if possible.

### V1 Synthesis

Controls how chunks are merged into groups and the final article:

```yaml
synthesis:
  temperature: 0.4            # Slightly higher for creative synthesis
  context_window: 64000       # Your LLM's total context window (tokens)
  prompt_overhead: 2000       # Tokens reserved for system prompt
  response_reserve: 8000      # Tokens reserved for LLM response
  group_target_tokens: 8000   # Tokens per group (same as max_tokens)
  final_chunk_size: 40000     # Tokens per final synthesis pass (0 = auto)
```

- `context_window` must match your model. Common values: 128000 (GPT-4o), 200000 (Claude), 32768 (many local models).
- `final_chunk_size`: How much of the total content the final synthesis sees at once. Set to 0 to auto-calculate from context_window minus overhead.

### V2 Configuration

V2 uses a **layered configuration** system. Profiles inherit from defaults and can override specific fields:

```yaml
v2:
  defaults:
    base_url: "http://localhost:58080/v1"  # Inherited by all profiles
    api_key: "local"
    model: "gpt-4o-mini"
    temperature: 0.2
    request_timeout_seconds: 300
    thinking: true                         # Enable reasoning effort

  profiles:
    mini_summary:
      prompt_file: "prompt_block_mini_summary.md"
      temperature: 0.1
      thinking: false

    cartography:
      prompt_file: "prompt_cartographer_map.md"
      thinking: true

    chapter_short:
      prompt_file: "prompt_chapter_short.md"
      temperature: 0.25
      thinking: true

    chapter_long:
      prompt_file: "prompt_chapter_detailed.md"
      temperature: 0.25
      thinking: true
```

**Key concept:** Each profile can independently override `model`, `temperature`, `base_url`, `api_key`, `request_timeout_seconds`, and `thinking`. Unset fields fall through to `defaults`. This lets you use a fast cheap model for mini-summaries and a powerful model for cartography.

#### V2 Blocking (Precise Chunking)

Controls how source text is split into blocks. There's one real path:

```
source text → split into overlapping windows of `window_tokens` size
            → send each window to LLM as line-numbered text
            → LLM returns semantic boundary lines
            → those lines become your blocks
```

If the LLM returns no boundaries (fails completely), it falls back to a simple mechanical split at ~1000 tokens — hardcoded, not configurable.

| Setting | What it controls | Example |
|---------|-----------------|---------|
| `window_tokens` | How much text you submit per LLM call | Send 16k tokens → LLM reads it line by line |
| `max_boundaries_per_window` | Max cuts the LLM can make in one window | 16 cuts per 16k window → blocks of ~1000 tokens minimum |
| `overlap_pct` | Fractional overlap between adjacent windows | 5% ensures boundaries near edges get a second look |

```yaml
v2:
  blocking:
    encoding_model: "gpt-4o-mini"     # Tokenizer
    window_tokens: 16000               # How much text per LLM call
    max_boundaries_per_window: 16      # Max cuts the LLM can return per call
    overlap_pct: 0.05                  # 5% overlap between windows
```

#### V2 Execution

```yaml
v2:
  execution:
    checkpoint_pct: 5.0                 # Save progress every N% (0 = every step, 100 = only at end)
    context_window: 128000              # Model's total context window
    prompt_overhead: 4000               # Tokens reserved for system prompts
    response_reserve: 8000              # Tokens reserved for LLM responses
```

- `checkpoint_pct`: At 5%, progress saves every 5% of work completed. Ctrl+C recovery costs at most 5% of redundant calls.
- `context_window` / `prompt_overhead` / `response_reserve`: Used to calculate available tokens for content. These should match your model's actual limits.

---

## Prompt Files

Rixie's pipeline is driven by **prompt files** — Markdown files that tell each stage's LLM call *how* to think and *what* to produce. They live alongside the code:

| Prompt File | Pipeline | Stage | Purpose |
|---|---|---|---|
| `v2/prompt_precise_chunk.md` | V2 | Cartography (Step 0) | LLM finds semantic boundaries in text windows |
| `v2/prompt_block_mini_summary.md` | V2 | Mini-summaries | Each block gets a one-sentence semantic fingerprint |
| `v2/prompt_cartographer_map.md` | V2 | Cartography (grouping) | LLM groups blocks into chapters via multi-turn validation |
| `v2/prompt_chapter_short.md` | V2 | Chapter summaries (short) | Concise, friendly overview of each chapter |
| `v2/prompt_chapter_detailed.md` | V2 | Chapter summaries (detailed) | In-depth extraction of each chapter |
| `v2/prompt_ultra_dense.md` | V2 | Overview / Abstract | One dense paragraph capturing the book's essence |
| `v1/distill_chunk_prompt.md` | V1 | Distillation | How each chunk is distilled |
| `v1/distill_final_prompt.md` | V1 | Final synthesis | How the final article is written |

### What You Can Safely Change

Every prompt is built from sections like `# Role`, `# Personality`, `# Goal`, `# Constraints`, `# Output`, etc. **Not all sections are equal.**

| Section | Safe to change? | Why |
|---------|----------------|-----|
| **Personality** | ✅ Yes | Voice, tone, character — "warm and curious", "sharp and direct", "academic and precise". This is yours to play with. |
| **Goal** | ⚠️ Partially | You can refine *what to focus on* or *what to prioritize*. But don't remove the core objective — the LLM needs to know its job. |
| **Role** | ⚠️ Partially | You can tweak the persona metaphor, but the role definition is tightly coupled to what the stage produces. |
| **Language** | ❌ No | Hard rule that keeps output in the source language. Breaking this breaks multilingual books. |
| **Constraints** | ❌ Mostly no | Many constraints encode pipeline expectations (e.g., "never reference the source as a text"). Removing them produces output that doesn't fit the pipeline's design. |
| **Output format** | ❌ No | Schema requirements (JSON structure, prose rules, length). Changing these breaks downstream stages that expect a specific format. |
| **Success criteria** | ❌ No | Quality guardrails. Removing them degrades output quality significantly. |
| **Stop rules** | ❌ No | Error-handling logic. Removing them causes failures on edge cases. |

### The Golden Rule

**Only change Personality and maybe tweak the Goal.** Everything else is structural wiring — it looks like prose but it's really code that the LLM reads to produce correctly formatted, pipeline-compatible output.

In practice:

- **`prompt_chapter_short.md`** — Change the Personality to match your desired voice. Refine the Goal to emphasize what you care about (e.g., "focus on actionable takeaways" or "emphasize conceptual connections"). Leave Constraints, Output, Success criteria, and Language untouched.
- **`prompt_chapter_detailed.md`** — Same. Change Personality and Goal emphasis. The rest is scaffolding.
- **`prompt_ultra_dense.md`** — Same pattern. Personality and Goal are yours.
- **All other prompts** — Better to not touch at all. `prompt_precise_chunk.md`, `prompt_block_mini_summary.md`, and `prompt_cartographer_map.md` have JSON schemas and pipeline logic woven into their instructions. Changing them risks breaking the pipeline.

### Example

If you want your chapter summaries to sound more academic:

```markdown
# Personality
Analytical, precise, measured. Like a senior researcher summarizing findings for a peer.

# Goal
Emphasize methodological rigor, evidence chains, and the logical structure of the argument.
```

If you want them more playful:

```markdown
# Personality
Playful, irreverent, conversational. Like a favourite teacher who makes everything click.

# Goal
Focus on the counter-intuitive twists and the "aha" moments.
```

Leave everything else in the file exactly as it is.

---

## Running the Pipeline

### V2 Pipeline (Recommended)

The V2 pipeline is a 6-stage progressive distillation system. Each stage builds on the last, and all stages are checkpointed for resumability.

```bash
# Process a single book
uv run rixie v2 input/my_book.epub

# Process ALL books in input/
uv run rixie v2

# Smoke test — process only the first 10 blocks (fast, useful for testing config)
uv run rixie v2 input/my_book.epub --max-blocks 10

# Show all available options
uv run rixie v2 --help
```

**Resumability:** Kill with Ctrl+C at any stage. Re-run the exact same command to resume from the last checkpoint. At most one checkpoint interval of redundant LLM calls.

**Output structure:**

```
output/v2/my-book-slug/
├── book.yaml                     # Full artifact (all stages in one file)
├── source.md                     # Normalized source text
├── my-book-slug.html             # Scrollytelling HTML viewer
└── my-book-slug.epub             # Progressive-disclosure EPUB
```

Open the `.html` file in a browser. Open the `.epub` in your e-reader. Generate a podcast from the workspace (see [V2 Podcast](#v2-podcast)).

### V1 Pipeline (Legacy)

The original Rixie pipeline. Stable and well-tested, now in maintenance mode.

```bash
# Process a single book
uv run rixie v1 input/my_book.epub

# Process ALL books in input/
uv run rixie v1

# Skip final merge step (groups only, no final article)
uv run rixie v1 input/my_book.epub --no-final

# Skip HTML export
uv run rixie v1 input/my_book.epub --no-html

# Skip EPUB export
uv run rixie v1 input/my_book.epub --no-epub

# Skip both
uv run rixie v1 input/my_book.epub --no-html --no-epub

# Show all available options
uv run rixie v1 --help
```

**Three levels of output:**

| Level | What | Where | Read Time |
|-------|------|-------|-----------|
| **1 — Chunks** | Raw per-chapter distillations. Full detail, every mental model. | `distilled/*.md` | ~20+ min |
| **2 — Groups** | Thematic clusters. Deduplicated, connected, cross-chapter patterns. | `synthesis/group_*.md` | ~10 min |
| **3 — Final** | One readable article. Plain language, flowing prose. | `final.md` | ~2 min |

**Output structure:**

```
output/v1/My_Book/
├── chunks/                   ← Smart chunks (respects chapters)
├── distilled/                ← Level 1: Per-chunk distillations
├── synthesis/                ← Level 2: Group distillations
├── final.md                  ← Level 3: Readable article
├── My_Book.html              ← HTML viewer with tabs
└── My_Book.epub              ← Standard EPUB3 export
```

---

## Audio Output

### V1 Audiobook

Converts V1 distillation output to MP3 using edge-tts (Microsoft neural voices, 400+ options).

```bash
# Interactive menu — pick book, content level, voice
uv run rixie audiobook

# Skip book selection (picks the only book)
uv run rixie audiobook --book "Thinking"

# Pick voice directly
uv run rixie audiobook --voice en-US-GuyNeural

# Adjust speed
uv run rixie audiobook --rate "+15%"

# Show all options
uv run rixie audiobook --help
```

**Output:**

| File | Content |
|------|---------|
| `audiobook/groups.mp3` | All groups combined into one track |
| `audiobook/final.mp3` | Final synthesis as one track |

If ffmpeg is installed, groups are generated segment-by-segment then merged for better quality.

### V2 Podcast

Generates two MP3 versions from a V2 workspace:

- **Short:** Title → Abstract → short chapter summaries (quick listen)
- **Long:** Title → Abstract → detailed chapter summaries (deep dive)

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

## Output Formats

### HTML Viewer

**V1:** Dark-themed, tabbed interface with three sections (Short Version, Groups, All Chunks). Features lazy-loaded markdown rendering and a theme switcher (White, Paper, Dusk, OLED, Dimmed, Midnight).

**V2:** Scrollytelling template with full artifact data embedded inline. The template owns all HTML/CSS/JS — Python just injects the JSON data.

Open the `.html` file directly in any browser. No server needed.

### EPUB Export

**V1:** Standard EPUB3 format with proper navigation. Linear structure with three sections. Works in any e-reader.

**V2:** Progressive-disclosure EPUB3 with `<details>` expandable sections. Title page → Abstract → Chapter summaries (short visible, detailed expandable) → End page. Beautiful typography with thematic styling.

### Audio

**V1:** Per-book MP3 tracks for groups and final synthesis via edge-tts.

**V2:** Dual-length podcast MP3s — short version (abstract + short summaries) for quick listening, long version (abstract + detailed summaries) for deep dives.

---

## Commands Cheatsheet

| Action | Command |
|--------|---------|
| Install dependencies | `uv sync` |
| V1 pipeline (all books) | `uv run rixie v1` |
| V1 pipeline (one book) | `uv run rixie v1 input/book.epub` |
| V2 pipeline (all books) | `uv run rixie v2` |
| V2 pipeline (one book) | `uv run rixie v2 input/book.epub` |
| V2 smoke test | `uv run rixie v2 input/book.epub --max-blocks 10` |
| Audiobook (V1) | `uv run rixie audiobook` |
| Podcast (V2) | `uv run python -m v2.podcast output/v2/slug` |
| Copy HTMLs to reading list | `uv run rixie reading-list` |
| Show help | `uv run rixie help` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |

---

## Makefile Reference

Common commands are also available through `make`:

```bash
make install          # uv sync
make v1               # Run V1 on all books
make v1-book B=file.epub     # V1 on a specific book
make v2               # Run V2 on all books
make v2-book B=file.epub     # V2 on a specific book
make v2-smoke B=file.epub    # V2 smoke test (10 blocks)
make audiobook        # Interactive audiobook
make podcast SLUG=slug       # V2 podcast
make reading-list     # Copy HTMLs to reading list
make lint             # ruff check
make format           # ruff format
make clean            # Remove caches
make clean-all        # Remove caches + .venv + uv.lock
make help             # Show all targets
```

---

## Project Structure

```
Rixie/
├── input/                              ← Drop books here
├── output/                             ← Pipeline output lands here
│   ├── v1/{book_name}/                 ← V1 pipeline output
│   └── v2/{book_slug}/                 ← V2 pipeline output
│
├── v1/                                 ← Legacy V1 pipeline
│   ├── process.py                      ← Pipeline orchestrator & CLI
│   ├── chunker.py                      ← Chapter-respecting chunking
│   ├── distiller.py                    ← LLM distillation per chunk
│   ├── synthesizer.py                  ← Group + final synthesis
│   ├── export_html.py                  ← HTML viewer export
│   ├── export_epub.py                  ← EPUB export
│   ├── distill_chunk_prompt.md         ← Chunk distillation prompt
│   └── distill_final_prompt.md         ← Final synthesis prompt
│
├── v2/                                 ← Progressive V2 pipeline
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
├── README.md                           ← This file
├── docs/GETTING_STARTED.md             ← Full getting started guide
├── uv.lock                             ← Dependency lock file
├── .python-version                     ← Python version pin (3.12)
├── .editorconfig                       ← Editor consistency
├── .gitignore
├── Makefile                            ← Common commands
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

## Supported Input Formats

| Format | Method | External Dependency |
|--------|--------|-------------------|
| `.md` | Direct processing | None |
| `.txt` | Direct processing | None |
| `.epub` | Auto-converts via pandoc | [pandoc](https://pandoc.org/installing.html) |
| `.pdf` | Auto-converts via pypdf | None |

---

> Everything in its place. Now go distill some books.
