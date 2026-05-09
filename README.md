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
| **Best for** | Stable, classic 3-level output | Chapter structure, audio podcasts, fine-grained control |

---

## See It In Action

Want to see what Rixie produces before running it? Here's the output of a full V2 distillation of **The Wealth of Nations** — Adam Smith's 1,000-page economic treatise, compressed into a browsable scrollytelling document:

> **[📄 The Wealth of Nations — Distilled](assets/adam-smith_the-wealth-of-nations.html)** (3.4 MB, open in browser)
> **[📱 EPUB for e-reader](assets/adam-smith_the-wealth-of-nations.epub)**

The HTML is a self-contained scrollytelling viewer with all chapters, summaries, and the abstract. The EPUB uses progressive-disclosure with expandable sections. Both were generated entirely by Rixie — no manual editing.

---

## V2 Pipeline (Recommended)

This is the pipeline you should use. Six stages, each building on the last, fully checkpointed so you can Ctrl+C and resume without losing progress.

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
│ Each block gets a one-sentence summary + useful/not  │
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

**Precise Chunking (Stage 1):** Instead of mechanical token-splitting, V2 sends overlapping token windows to the LLM as line-numbered text. The LLM identifies natural semantic boundaries (paragraph breaks, topic shifts, section transitions). The result: blocks that never split mid-thought.

**Multi-Turn Cartographer (Stage 3):** Chapter grouping happens in a feedback loop. The LLM proposes chapter boundaries, validation checks for gaps (uncovered blocks) and overlaps (blocks in multiple chapters), and errors are fed back for up to 6 correction rounds. This produces clean, consistent chapter maps.

**Checkpoint Resumability:** Every stage saves progress at configurable intervals (default: every 5% of work completed). Crashes and Ctrl+C cost at most one checkpoint interval of redundant LLM calls. Resume by re-running the exact same command.

**Per-Profile LLM Settings:** Each pipeline stage can use a different model, temperature, or thinking mode. Run cheap models for bulk work (mini-summaries) and expensive ones for quality-critical stages (cartography, chapter summaries).

---

## V1 Pipeline (Legacy)

The original Rixie pipeline. Stable and well-tested. Produces three levels of output, from deep to digestible:

| Level | What | Where | Read Time |
|-------|------|-------|-----------|
| **1 — Chunks** | Raw per-chapter distillations. Full detail, every mental model extracted. | `distilled/*.md` | ~20+ min |
| **2 — Groups** | Thematic clusters. Deduplicated, connected, cross-chapter patterns emerge. | `synthesis/group_*.md` | ~10 min |
| **3 — Final** | One readable article. Plain language, analogies, flowing prose. The "vibe check." | `final.md` | ~2 min |

Start with the Final for the big picture. Go to Groups for depth. Dive into Chunks when you want *everything*.

---

## Feature Highlights

- **LLM-powered extraction** — Finds mental models, heuristics, and actionable knowledge. Not a summary — a cognitive upgrade.
- **Two pipelines** — V2 for progressive, checkpointed distillation with chapter-level structure; V1 for stable, well-tested three-level output.
- **Precise chunking** — V2 uses the LLM itself to find semantic boundaries. No mid-thought splits.
- **Multi-turn validation** — Chapter grouping detects gaps and overlaps, feeds corrections back to the LLM for up to 6 rounds.
- **Checkpoint resumability** — Kill it anytime with Ctrl+C. Re-run and it picks up where it left off. At most one checkpoint interval lost.
- **Audio output** — Audiobooks (V1) and dual-length podcasts (V2) via edge-tts with 400+ neural voices.
- **Multiple formats** — Read in your browser (HTML), on your e-reader (EPUB), or listen on the go (MP3).
- **Any LLM backend** — OpenAI, local (Ollama, LM Studio, vLLM), or any OpenAI-compatible endpoint.
- **Per-stage model control** — Each pipeline stage can use a different model, temperature, or reasoning mode.

---

## Quickstart

```bash
# 1. Clone
git clone <repo-url> Rixie
cd Rixie

# 2. Install (uv handles Python version + deps + venv)
uv sync

# 3. Configure your LLM
#    Edit config.yaml — set base_url, api_key, and model for your endpoint

# 4. Drop a book in input/
cp my_book.epub input/

# 5. Run the V2 pipeline
uv run rixie v2 input/my_book.epub
```

Output lands in `output/v2/my-book-slug/` — open the `.html` file in a browser or the `.epub` in your reader.

---

## Next Steps

This gets you started. For complete coverage of configuration options, pipeline flags, audio output, output formats, and the full command cheatsheet, see:

> **[📖 Getting Started Guide](docs/GETTING_STARTED.md)**

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 lirrensi.
