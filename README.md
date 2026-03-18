# Rixie

Too long did not Rixie

<img src="assets/rixie.jpg" alt="Rixie" width="100%">

**Throw books in. Get distilled knowledge out.**

Rixie is an LLM-powered book distiller. It reads your book (Markdown, EPUB, or text), breaks it into chunks, and runs each chunk through an LLM that extracts only the *functional* knowledge — mental models, actionable heuristics, bullshit detectors, and the one seed principle that rebuilds the whole argument.

The output isn't a summary. It's a **cognitive upgrade** — what the book makes you *capable of*, not what it said.

### Three Levels of Distillation

Every book produces three layers of output, from deep to digestible:

| Level | What | Where | Read Time |
|-------|------|-------|-----------|
| **1 — Chunks** | Raw per-chapter distillations. Full detail, every mental model extracted. | `distilled/*.md` | ~20+ min |
| **2 — Groups** | Thematic clusters. Deduplicated, connected, cross-chapter patterns emerge. | `synthesis/group_*.md` | ~10 min |
| **3 — Final** | One readable article. Plain language, analogies, flowing prose. The "vibe check." | `final.md` | ~2 min |

Start with the Final for the big picture. Go to Groups for depth. Dive into Chunks when you want *everything*.

---

## Get Started

### 1. Clone & Install

```bash
git clone <repo-url> Rixie
cd Rixie
uv sync
```

That's it. `uv` handles everything — Python version, dependencies, all of it.

### 2. Configure Your LLM

Edit `config.yaml` — this is the only file you need to touch:

```yaml
llm:
  base_url: "http://localhost:58080/v1"  # Your LLM endpoint (OpenAI-compatible)
  api_key: "local"                       # API key (use "local" for no auth)
  model: "gpt-4o-mini"                   # Model name
  temperature: 0.3                       # 0 = deterministic, 1 = creative
```

Point `base_url` and `model` at whatever LLM you're running — local (Ollama, LM Studio, vLLM) or remote (OpenAI, etc.). If your model has a different context window, update the `synthesis` section too:

```yaml
synthesis:
  context_window: 64000      # Your model's max context
  prompt_overhead: 2000      # Reserved for system prompt
  response_reserve: 8000     # Reserved for response
  group_target_tokens: 8000  # Tokens per group (controls granularity)
```

### 3. Drop a Book In

Put your book in the `input/` folder:

```bash
cp my_book.md input/
# or
cp my_book.epub input/
```

Supported formats: `.md`, `.txt`, `.epub` (requires [pandoc](https://pandoc.org/installing.html)).

### 4. Run It

```bash
uv run python process.py
```

That's the whole pipeline — chunk, distill, synthesize, export. It's resumable too: kill it anytime with Ctrl+C and re-run, it picks up where it left off.

### 5. Find Your Output

```
output/
└── my_book/
    ├── chunks/          # Smart chunks (respects chapters)
    ├── distilled/       # Level 1: Per-chunk distillations
    ├── synthesis/       # Level 2: Group distillations (thematic clusters)
    ├── final.md         # Level 3: Readable article (2-min vibe check)
    ├── my_book.html     # Beautiful HTML viewer (dark theme, tabs, accordions)
```

Open the `.html` file in a browser. Done.

### (Optional) Tune the Prompts

Three prompt files at the root control how the LLM thinks:

| File | What it does | Output level |
|------|-------------|--------------|
| `distill_chunk_prompt.md` | Extracts functional knowledge from each chunk | Level 1 — Chunks |
| `distill_group_prompt.md` | Merges chunks into thematic groups (dense) | Level 2 — Groups |
| `distill_final_prompt.md` | Rewrites groups into a readable article | Level 3 — Final |

Edit them to change what kind of knowledge gets extracted. The defaults focus on mental models, operations, immune responses, and seed principles.

---

## How It Works

Three stages, each producing a different level of insight:

### Stage 1: Chunking
The book is split into chunks that respect natural boundaries (chapters, sections) while staying within a token limit.

### Stage 2: Per-Chunk Distillation → Level 1 (Chunks)
Each chunk goes through the LLM individually. It extracts:
- **Receptors** — new mental models and lenses
- **Operations** — actionable heuristics and procedures
- **Immune Responses** — bullshit detection patterns
- **Generator** — the one principle that rebuilds the whole book

Anecdotes and examples get stripped. Only functional knowledge survives.

### Stage 3: Synthesis → Level 2 (Groups) + Level 3 (Final)

**Group Synthesis** — Chunks pack into ~8k token groups and merge. Deduplicated, connected, elevated. Cross-chunk patterns become visible. Multiple groups preserve detail without cramming everything into one output.

**Final Synthesis** (optional, `--final`) — All groups get rewritten into a single, readable article. Plain language, analogies, flowing prose. Prioritizes connection and readability over density. The "explain it to a friend" version.

### Context Window & Group Size

Two settings control the granularity:

```yaml
synthesis:
  context_window: 64000        # LLM's max context (hard limit)
  group_target_tokens: 8000    # Target tokens per group (controls granularity)
```

- **`group_target_tokens`** — Each group packs as many chunks as fit in this window. Smaller = more groups = more detail. Same value as chunking works well.
- **`context_window`** — Your LLM's hard limit. Only matters for the final synthesis step.

---

## Commands

### Process everything in input/
```bash
uv run python process.py
```

### Process a specific book
```bash
uv run python process.py input/my_book.md
uv run python process.py input/my_book.epub
```

### Skip final merge step
```bash
uv run python process.py --no-final
```

### Skip HTML export
```bash
uv run python process.py --no-html
```

### Run individual steps manually

```bash
# Just chunk a book
uv run python chunker.py input/my_book.md output/my_book/chunks

# Just distill existing chunks
uv run python distiller.py output/my_book/chunks output/my_book/distilled

# Just synthesize (groups only)
uv run python synthesizer.py output/my_book/distilled

# Just synthesize (with final merge)
uv run python synthesizer.py output/my_book/distilled --final

# Just export HTML
uv run python export_html.py output/my_book "My Book Title"
```

---

## Audiobook

Convert distillation output to audio using [edge-tts](https://github.com/rany2/edge-tts) (Microsoft neural voices, 400+ options).

```bash
# Interactive menu — pick book, content, voice
uv run python audiobook.py

# Skip book selection if only one book
uv run python audiobook.py --book "Thinking"

# Pick voice directly
uv run python audiobook.py --voice "en-US-GuyNeural"

# Adjust speed
uv run python audiobook.py --rate "+15%"
```

### What you get

| File | Content |
|------|---------|
| `audiobook/groups.mp3` | All groups combined into one track |
| `audiobook/final.mp3` | Final synthesis as one track |

### Available voices

| Key | Voice |
|-----|-------|
| `aria` | 🇺🇸 Aria (Female, warm) |
| `jenny` | 🇺🇸 Jenny (Female, friendly) |
| `guy` | 🇺🇸 Guy (Male, natural) |
| `eric` | 🇺🇸 Eric (Male, calm) |
| `sonia` | 🇬🇧 Sonia (Female, British) |
| `ryan` | 🇬🇧 Ryan (Male, British) |

Or use any [edge-tts voice name](https://github.com/rany2/edge-tts#supported-voices) directly.

> 💡 If ffmpeg is installed, groups are generated segment-by-segment then merged for better audio. Without ffmpeg, it's one continuous generation.

---

## Supported Input

| Format | Method |
|--------|--------|
| `.md` | Direct processing |
| `.epub` | Auto-converts via pandoc (must be installed) |
| `.txt` | Direct processing |

For EPUB support, install [pandoc](https://pandoc.org/installing.html).
For audio merging, install [ffmpeg](https://ffmpeg.org/download.html).

## Dependencies

```bash
# Managed via uv (auto-installed)
openai, pyyaml, tiktoken, pydantic, edge-tts
```

---

## Project Structure

```
Rixie/
├── input/                          ← Drop books here
├── output/
│   └── {book_name}/
│       ├── chunks/                 ← Smart chunks
│       ├── distilled/              ← Per-chunk distillations
│       ├── synthesis/              ← Group distillations
│       ├── final.md                ← Level 3: Readable article
│       ├── {book_name}.html        ← HTML viewer (marked.js)
│       └── audiobook/              ← 🎧 Audio output
│           ├── groups.mp3
│           └── final.mp3
│
├── config.yaml                     ← LLM settings (edit this)
├── distill_chunk_prompt.md         ← Per-chunk prompt
├── distill_group_prompt.md         ← Per-group prompt
├── distill_final_prompt.md         ← Final merge prompt
│
├── process.py                      ← 🚀 Main pipeline
├── chunker.py                      ← Smart chunking
├── distiller.py                    ← LLM distillation
├── synthesizer.py                  ← Group + final synthesis
├── export_html.py                  ← HTML export (marked.js)
└── audiobook.py                    ← 🎧 Audiobook generator
```
