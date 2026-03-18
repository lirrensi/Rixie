# 📚 Rixie

<img src="assets/rixie.jpg" alt="Rixie" width="100%">

Throw books in, get distilled knowledge out. That's it.

## Philosophy

Most book summarizers give you "what the author said." Rixie gives you "what the book makes you capable of."

The distillation focuses on four dimensions of knowledge:

| Dimension | Question | Output |
|-----------|----------|--------|
| **Receptors** | What can I now *see* that I was blind to before? | New mental models and lenses |
| **Operations** | What can I now *do* that I couldn't do before? | Actionable heuristics and procedures |
| **Immune Responses** | What can I now *recognize and reject*? | Bullshit detection patterns |
| **Generator** | If the book vanished, what one principle rebuilds it? | The seed of the entire argument |

The goal isn't to remember the book. It's to *become someone who thinks differently* because they read it. Every insight must pass the "nugget vs. platitude" test — common sense gets discarded, only cognitive upgrades survive.

## How It Works

Rixie processes books through three stages of distillation, each one compressing and refining the knowledge:

### Stage 1: Chunking
The book is split into chunks that respect natural boundaries (chapters, sections) while staying within a token limit. This keeps each distillation focused on a coherent piece of the argument.

### Stage 2: Per-Chunk Distillation
Each chunk goes through the distillation prompt individually. The LLM extracts receptors, operations, immune responses, and a "seed principle" — stripping away anecdotes and examples, keeping only the functional knowledge.

### Stage 3: Synthesis (Group → Final)
This is where the magic happens. The distilled chunks are merged in two passes:

**Group Synthesis** — Chunks are combined into thematic groups. Deduplicated, connected, and elevated. What you get is tighter than the individual distillations because patterns across chunks become visible.

**Final Merge** (optional) — All groups merge into one definitive document. Organized by theme, not chapter order. This is the "if you only read one thing" version.

### Context Window = Granularity Control

The `context_window` setting in `config.yaml` controls how many chunks get grouped together:

```
synthesis:
  context_window: 64000      # Your LLM's context window size
  prompt_overhead: 2000      # Reserved for system prompt
  response_reserve: 8000     # Reserved for LLM response
```

Rixie calculates usable space (`context_window - prompt_overhead - response_reserve`) and fits as many distilled chunks as possible into each group. So:

- **Smaller context window** → more groups, more granular, preserves more detail
- **Larger context window** → fewer groups, more synthesis, broader connections

If your LLM supports 128k context, try doubling it. You'll get fewer, richer groups that see bigger patterns. If you want to preserve more detail, reduce it. The pipeline adapts automatically.

## Quick Start

```bash
# 1. Drop a book into input/
cp my_book.md input/

# 2. Run it
uv run python process.py

# 3. Find your output in output/{book_name}/
#    - chunks/       → Smart chunks
#    - distilled/    → Per-chunk distillations  
#    - synthesis/    → Group distillations
#    - final.md      → Final merged synthesis
#    - index.html    → Beautiful HTML viewer (tabs + accordions)
```

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

### Combine flags
```bash
uv run python process.py --no-final --no-html
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

## Config

Edit `config.yaml` to change LLM settings:

```yaml
llm:
  base_url: "http://localhost:58080/v1"  # Your LLM endpoint
  api_key: "local"                       # API key
  model: "gpt-4o-mini"                   # Model name
  temperature: 0.3                       # 0 = deterministic, 1 = creative

chunking:
  max_tokens: 8000           # Max tokens per chunk

synthesis:
  temperature: 0.4           # Higher for creative synthesis
  context_window: 64000      # Your LLM's context window

output:
  generate_html: true        # Export HTML after synthesis
  generate_final: true       # Run final merge step
```

## Prompts

Three prompt files at the root — edit them anytime:

| File | What it does |
|------|-------------|
| `distill_chunk_prompt.md` | Distills each chunk individually |
| `distill_group_prompt.md` | Merges chunks into thematic groups |
| `distill_final_prompt.md` | Merges groups into final synthesis |

## Output Structure

```
output/
└── My_Book/
    ├── chunks/
    │   ├── 000_Introduction.md
    │   ├── 001_Chapter_One.md
    │   ├── ...
    │   └── MANIFEST.md
    ├── distilled/
    │   ├── 000_distilled.md
    │   ├── 001_distilled.md
    │   └── ...
    ├── synthesis/
    │   ├── group_01.md
    │   ├── group_02.md
    │   └── ...
    ├── final.md
    ├── index.html
    └── audiobook/
        ├── groups.mp3
        └── final.mp3
```

## HTML Viewer

The exported `index.html` embeds raw markdown and uses [marked.js](https://marked.js.org/) from CDN for client-side rendering. Dark-themed, responsive, handles tables/code/lists perfectly.

- **⚡ Short Version** — Final synthesis, clean and scannable
- **📖 Long Version** — Group distillations as expandable accordions (lazy-rendered on open)

Open it in any browser. Single file, just needs internet for CDN. Share it anywhere.

## Resumability

Everything is resumable. Kill the process anytime (Ctrl+C) and re-run — it picks up exactly where it left off:

- Chunks already created → skipped
- Distillations already done → skipped
- Groups already synthesized → skipped
- Final already merged → skipped

## Supported Input

| Format | Method |
|--------|--------|
| `.md` | Direct processing |
| `.epub` | Auto-converts via pandoc (must be installed) |
| `.txt` | Direct processing |

## Dependencies

```bash
# Managed via uv (auto-installed)
openai, pyyaml, tiktoken, pydantic, edge-tts
```

For EPUB support, install [pandoc](https://pandoc.org/installing.html).
For audio merging, install [ffmpeg](https://ffmpeg.org/download.html).

# 📚 BookConvert — Final Structure
```text
Rixie/
├── input/                          ← Drop books here
├── output/
│   └── {book_name}/
│       ├── chunks/                 ← Smart chunks
│       ├── distilled/              ← Per-chunk distillations
│       ├── synthesis/              ← Group distillations
│       ├── final.md                ← Final synthesis
│       ├── index.html              ← HTML viewer (marked.js)
│       └── audiobook/              ← 🎧 Audio output
│           ├── groups.mp3
│           └── final.mp3
│
├── config.yaml                     ← LLM settings
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