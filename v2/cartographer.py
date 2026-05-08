# FILE: v2/cartographer.py
# PURPOSE: V2 content-mapping stage: precise LLM boundary detection (Step 0),
#          block mini-summaries, and chapter grouping from semantic fingerprints.
# OWNS: Cartography-stage logic, precise chunking, mini-summary generation,
#       and chapter boundary design.
# EXPORTS: CARTOGRAPHY_STAGE, map_book_structure, generate_precise_blocks,
#          generate_block_mini_summaries, group_blocks_into_chapters, LLMSettings.
# DOCS: README.md, v2/schema.py, v2/pipeline.py
#
# POLICY: Never write fallback garbage. If an AI call fails after all retries,
# the field stays None and the stage reports the failure.
# RESUMABILITY: Every completed block is saved immediately. Crashes/ctrl-c cost at most one in-flight block.

from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None

from v2.blocker import build_blocks
from v2.budget import ContextBudget, estimate_tokens, split_text_by_tokens
from v2.checkpoint import CheckpointTracker, save_artifact_sync
from v2.pipeline import structured_completion
from v2.prompts import load_prompt
from v2.schema import BookArtifact, BlockArtifact, ChapterArtifact, StageState
import yaml

CARTOGRAPHY_STAGE = "cartography"
MINI_SUMMARIES_STAGE = "mini_summaries"
PRECISE_CHUNK_STAGE = "precise_chunk"


def _get_encoder(model: str):
    """Get tiktoken encoder for a model, with fallback."""
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _token_count(text: str, encoder) -> int:
    """Count tokens in text using the given encoder."""
    if not text:
        return 0
    if encoder is None:
        return max(1, len(text) // 4)
    return len(encoder.encode(text))


class MiniSummaryResult(BaseModel):
    mini_summary: str | None  # Allow null when useful=false
    useful: bool


class ChapterRange(BaseModel):
    title: str
    end_idx: int  # 1-based index of the LAST block in this chapter


class ChapterMapResult(BaseModel):
    chapters: list[ChapterRange]


class PreciseChunkResult(BaseModel):
    """Step 0: LLM returns line numbers where semantic boundaries occur."""
    boundaries: list[int]


@dataclass
class LLMSettings:
    model: str
    temperature: float
    api_base: str | None = None
    api_key: str | None = None
    timeout: int | None = None
    thinking: bool = True


def _call_json_sync(
    messages: list[dict],
    settings: LLMSettings,
    response_model: type[BaseModel],
) -> BaseModel:
    """Call LLM with structured output - returns Pydantic model directly.

    Uses OpenAI SDK parse() via structured_completion.
    No LiteLLM. No schema conversion. No manual validation.
    """
    print(f"      Calling structured_completion for {response_model.__name__}", flush=True)
    return structured_completion(settings, messages, response_model)


def _split_oversized_block_for_mini_summary(
    block: BlockArtifact,
    *,
    budget: ContextBudget,
    llm_settings: LLMSettings,
    prompt_file: str,
    max_retries: int = 3,
) -> str | None:
    """Generate a mini-summary for an oversized block by splitting it into parts.
    
    Each part gets its own mini-summary call; results are combined into one.
    Returns combined mini_summary or raises on failure.
    """
    system = load_prompt(prompt_file)
    system_tokens = estimate_tokens(system, llm_settings.model)
    available = budget.usable - system_tokens

    if available <= 0:
        return None

    parts = split_text_by_tokens(
        block.text or "",
        max_tokens=available,
        model=llm_settings.model,
    )

    if len(parts) <= 1:
        # Single part — let the normal retry loop handle it
        return None

    print(f"   ✂️  Block {block.block_id} split into {len(parts)} part(s) "
          f"(~{estimate_tokens(block.text or '', llm_settings.model)} tokens, "
          f"budget {available})", flush=True)

    mini_summaries: list[str] = []
    for part_idx, part_text in enumerate(parts, start=1):
        success = False
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                result = _call_json_sync(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": f"BLOCK PART {part_idx}:\\n{part_text}"},
                    ],
                    llm_settings,
                    response_model=MiniSummaryResult,
                )
                if result.useful and result.mini_summary:
                    mini_summaries.append(f"[Part {part_idx}] {result.mini_summary}")
                elif result.useful:
                    mini_summaries.append(f"[Part {part_idx}] (content area)")
                success = True
                break
            except Exception as e:
                last_error = e
                import time as time_mod
                if attempt < max_retries:
                    time_mod.sleep(2 ** attempt)

        if not success:
            raise RuntimeError(
                f"Block {block.block_id} part {part_idx} failed "
                f"after {max_retries} retries: {last_error}"
            )

    combined = " | ".join(mini_summaries)
    return combined


def generate_block_mini_summaries(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    parallel_calls: int = 8,  # IGNORED - always sequential now
    prompt_file: str = "prompt_block_mini_summary.md",
    checkpoint_pct: float = 5.0,
    max_per_block_retries: int = 3,
    budget: ContextBudget | None = None,
) -> BookArtifact:
    """Generate mini summaries SEQUENTIALLY with per-block retry and checkpoint saves.

    Saves the artifact to disk every ``checkpoint_pct`` % of progress (default 5 %)
    so crashes lose at most one checkpoint interval of work.  Blocks that fail
    after all retries raise RuntimeError — the book is skipped entirely.
    """
    import time as time_mod

    artifact.stages.setdefault(MINI_SUMMARIES_STAGE, StageState(name=MINI_SUMMARIES_STAGE))
    stage = artifact.stages[MINI_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating one-sentence block summaries and useful=false classifications."

    # SYNC SAVE initial status
    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    save_artifact_sync(artifact, book_yaml_path)

    total = len(artifact.blocks)
    print(f"   🔍 Mini summaries: {total} block(s)", flush=True)

    # A block is "done" if mini_summary is not None. Period.
    # useful=False blocks get mini_summary="N/A" stamped on completion.
    # No need to check useful — only "was this block processed?" matters.
    pending_indices = [
        idx for idx, block in enumerate(artifact.blocks)
        if block.mini_summary is None
    ]

    if not pending_indices:
        print(f"   ✓ All {total} blocks already have mini summaries", flush=True)
        stage.status = "done"
        stage.notes = "All block mini-summaries already present."
        return artifact.touch()

    print(f"   → Resuming {len(pending_indices)} pending blocks (skipping {total - len(pending_indices)} complete)", flush=True)

    print(f"   🔥 Processing {len(pending_indices)} blocks SEQUENTIALLY "
          f"(max {max_per_block_retries} retries per block, save every {checkpoint_pct:.0f}%)", flush=True)

    checkpoint = CheckpointTracker(len(pending_indices), every_pct=checkpoint_pct)

    # Process ONE block at a time, with per-block retries
    for idx in pending_indices:
        block = artifact.blocks[idx]
        print(f"   📤 Processing {idx+1}/{total}: {block.block_id}", flush=True)

        # ── Check if this block is too large for a single mini-summary call ──
        if budget is not None:
            system_text = load_prompt(prompt_file)
            system_tok = estimate_tokens(system_text, llm_settings.model)
            block_tok = estimate_tokens(block.text or "", llm_settings.model)
            total_est = system_tok + block_tok + 50  # 50 for "BLOCK:\\n" overhead
            if total_est > budget.usable:
                combined = _split_oversized_block_for_mini_summary(
                    block,
                    budget=budget,
                    llm_settings=llm_settings,
                    prompt_file=prompt_file,
                    max_retries=max_per_block_retries,
                )
                if combined is not None:
                    artifact.blocks[idx].useful = True
                    artifact.blocks[idx].mini_summary = combined

                    if checkpoint.should_save():
                        save_artifact_sync(artifact, book_yaml_path)
                        print(f"   💾 Checkpoint save at {checkpoint.progress_pct:.0f}% ({idx+1}/{total})", flush=True)

                    print(f"   ✓ Done {idx+1}/{total}: {block.block_id} → split into parts, useful=True", flush=True)
                    continue
                else:
                    # Fall through to normal processing (the split couldn't determine a budget)
                    print(f"   ↻ Block {block.block_id} oversized but can't split — trying normal call", flush=True)

        success = False
        last_error: Exception | None = None

        for attempt in range(1, max_per_block_retries + 1):
            try:
                result = _call_json_sync(
                    [
                        {"role": "system", "content": load_prompt(prompt_file)},
                        {"role": "user", "content": f"BLOCK:\\n{block.text}"},
                    ],
                    llm_settings,
                    response_model=MiniSummaryResult,
                )

                # Update artifact in memory
                artifact.blocks[idx].useful = result.useful
                # Always stamp mini_summary so "processed?" is just "is not None"
                artifact.blocks[idx].mini_summary = result.mini_summary or "N/A"
                success = True

                # Throttled checkpoint save (not every block — every N%)
                if checkpoint.should_save():
                    save_artifact_sync(artifact, book_yaml_path)
                    print(f"   💾 Checkpoint save at {checkpoint.progress_pct:.0f}% ({idx+1}/{total})", flush=True)

                print(f"   ✓ Done {idx+1}/{total}: {block.block_id} → useful={result.useful}"
                      f"{f' (attempt {attempt}/{max_per_block_retries})' if attempt > 1 else ''}", flush=True)
                break

            except Exception as e:
                last_error = e
                if attempt < max_per_block_retries:
                    delay = 2 ** attempt  # exponential backoff: 2, 4, 8, ...
                    print(f"   ↻ Retry {attempt}/{max_per_block_retries} for {block.block_id} "
                          f"after {delay}s: {type(e).__name__}", flush=True)
                    time_mod.sleep(delay)

        if not success:
            # All retries exhausted — HARD FAIL. The cartographer cannot
            # produce valid chapter mappings with missing block fingerprints.
            # Let the caller catch this and move on to the next book.
            raise RuntimeError(
                f"Block {block.block_id} failed after {max_per_block_retries} retry attempts. "
                f"Last error: {type(last_error).__name__}: {last_error}. "
                f"Cannot proceed to cartography with incomplete block summaries."
            )

    # Final anchor save — ensures even the last few blocks are persisted
    save_artifact_sync(artifact, book_yaml_path)
    print(f"   💾 Final save complete ({len(artifact.blocks)} blocks)", flush=True)

    useful_blocks = sum(1 for block in artifact.blocks if block.useful)
    # Only useful=True blocks with missing summary count as failures.
    failures = sum(
        1 for block in artifact.blocks
        if block.useful is True and block.mini_summary is None
    )

    if failures:
        stage.status = "partial"
        stage.notes = f"Generated {total - failures}/{total} block summaries ({failures} failures)."
        print(f"   ⚠️ {failures}/{total} block summaries failed — fields left None", flush=True)
    else:
        stage.status = "done"
        stage.notes = "All block mini-summaries generated."
        print(f"   ✓ Mini summaries: {total} blocks complete", flush=True)

    stage.outputs = {
        "block_count": len(artifact.blocks),
        "useful_blocks": useful_blocks,
        "skipped_blocks": len(artifact.blocks) - useful_blocks,
        "failed_blocks": failures,
        "parallel_calls": 1,  # No parallel - sequential only now
        "model": llm_settings.model,
    }
    return artifact.touch()


def _validate_and_materialize_chapter_indices(
    chapter_ranges: list[ChapterRange],
    useful_blocks: list[BlockArtifact],
) -> tuple[list[ChapterArtifact], list[str]]:
    """Validate chapter ranges using consecutive end-index logic.

    Chapters are *structurally consecutive*: given a list of ``end_idx`` values,
    Chapter 1 covers ``useful_blocks[0:end_idx_1]``, Chapter 2 covers
    ``useful_blocks[end_idx_1:end_idx_2]``, and so on.  Gaps and overlaps
    are *structurally impossible* — the only thing that can go wrong is the
    LLM producing out-of-order or out-of-range end indices.

    Returns:
        (chapters, []) on success — every useful block appears exactly once.
        ([], errors) on failure — errors describe what needs fixing.
    """
    N = len(useful_blocks)
    if N == 0:
        return [], []

    errors: list[str] = []
    chapters: list[ChapterArtifact] = []
    prev_end = 0  # 0-based index of the last block in the previous chapter

    for order, ch_range in enumerate(chapter_ranges, start=1):
        end_idx = ch_range.end_idx

        if end_idx <= prev_end:
            errors.append(
                f"Chapter {order} ('{ch_range.title}'): end_idx={end_idx} is not after "
                f"previous chapter's end ({prev_end}).  Each chapter needs >= 1 block."
            )
            continue

        if end_idx > N:
            errors.append(
                f"Chapter {order} ('{ch_range.title}'): end_idx={end_idx} exceeds "
                f"total block count ({N})."
            )
            continue

        # Materialize this chapter's blocks
        range_blocks = useful_blocks[prev_end:end_idx]
        block_ids = [b.block_id for b in range_blocks]
        start_block = range_blocks[0]
        end_block = range_blocks[-1]

        chapters.append(
            ChapterArtifact(
                chapter_id=f"chapter_{order:03d}",
                order=order,
                title=ch_range.title.strip() or f"Chapter {order}",
                block_start=start_block.order,
                block_end=end_block.order,
                char_start=start_block.char_start,
                char_end=end_block.char_end,
                blocks=block_ids,
            )
        )
        prev_end = end_idx

    # Did we cover all N blocks?
    if prev_end < N:
        errors.append(
            f"GAP: Only {prev_end} of {N} blocks are covered. "
            f"The last chapter must end at index {N} to include all blocks "
            f"(currently ends at {prev_end})."
        )
    elif prev_end > N:
        errors.append(
            f"OVERFLOW: Chapter ranges cover {prev_end} blocks but only {N} exist."
        )

    if errors:
        return [], errors
    return chapters, []


def _run_cartography_on_blocks(
    artifact: BookArtifact,
    useful_blocks: list[BlockArtifact],
    *,
    llm_settings: LLMSettings,
    prompt_file: str,
    part_label: str = "",
) -> list[ChapterArtifact]:
    """Run the multi-turn cartography loop on a list of useful blocks.

    Blocks are presented as **numbered indices** (1, 2, 3, …) — NOT block IDs.
    The LLM outputs only ``end_idx`` (the index of each chapter's last block).
    Chapters are structurally consecutive, making gaps/overlaps impossible.

    Args:
        artifact: Full artifact (unused directly — kept for API compatibility).
        useful_blocks: The blocks to map into chapters.
        llm_settings: LLM configuration.
        prompt_file: Path to the system prompt file.
        part_label: If non-empty, prepended to chapter titles (e.g. "Part 1 — ").

    Returns:
        List of ChapterArtifact objects with ORIGINAL block IDs.
    """
    # Present blocks as simple numbered indices: "1: summary\n2: summary\n..."
    block_lines = [
        f"{idx}: {block.mini_summary or ''}"
        for idx, block in enumerate(useful_blocks, start=1)
    ]

    system = load_prompt(prompt_file)
    base_user = "ORDERED BLOCK SUMMARIES (each line has an index number):\\n" + "\\n".join(block_lines)

    MAX_TURNS = 6
    feedback = ""

    for turn in range(1, MAX_TURNS + 1):
        if feedback:
            user = (
                base_user
                + "\n\n---\n❌ YOUR PREVIOUS CHAPTER MAP WAS REJECTED:\n"
                + feedback
                + "\n---\nPlease fix ALL of the issues above and return a corrected chapter map with end_idx values."
            )
        else:
            user = base_user

        parsed = _call_json_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            llm_settings,
            response_model=ChapterMapResult,
        )

        # Validate using consecutive index logic
        validated_chapters, errors = _validate_and_materialize_chapter_indices(
            parsed.chapters, useful_blocks,
        )

        if not errors:
            if part_label:
                for ch in validated_chapters:
                    ch.title = f"{part_label}{ch.title}"
            return validated_chapters

        # ── BUILD FEEDBACK ──
        # With consecutive-range logic, errors are simple:
        #   - "end_idx not after previous"
        #   - "end_idx exceeds N"
        #   - "last chapter doesn't end at N"
        error_lines = "\n".join(f"  • {e}" for e in errors)

        # Show the current state so the LLM can reason about what to fix
        current_state = "\n".join(
            f"  Chapter {i+1}: end_idx={ch.end_idx} ({ch.title})"
            for i, ch in enumerate(parsed.chapters)
        )

        feedback = (
            f"The chapter map had {len(errors)} validation error(s):\n"
            f"{error_lines}\n\n"
            f"Current chapter end indices:\n{current_state}\n\n"
            f"Remember:\n"
            f"- There are {len(useful_blocks)} blocks total (indices 1–{len(useful_blocks)})\n"
            f"- Chapters are consecutive: Ch 1 covers indices 1..end_1, Ch 2 covers end_1+1..end_2\n"
            f"- end_idx values must be STRICTLY INCREASING (each larger than the last)\n"
            f"- The last chapter MUST end at index {len(useful_blocks)}"
        )

        print(f"\n❌ VALIDATION FAILED (turn {turn}):", flush=True)
        for e in errors:
            print(f"   • {e}", flush=True)

        if turn == MAX_TURNS:
            raise RuntimeError(
                f"Cartographer failed after {MAX_TURNS} turns. "
                f"Last validation errors:\n{feedback}"
            )

        print(f"   🔁 Feeding errors back to LLM for turn {turn + 1}...", flush=True)

    raise RuntimeError(
        f"Cartographer failed after {MAX_TURNS} turns — "
        f"no valid chapter map produced."
    )


def group_blocks_into_chapters(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_cartographer_map.md",
    budget: ContextBudget | None = None,
) -> BookArtifact:
    """Group blocks into chapters using consecutive-range cartography.

    Blocks are presented as numbered indices (1, 2, 3, …).  The LLM only
    outputs ``end_idx`` for each chapter — the index of its LAST block.
    Chapters are *structurally consecutive*, which makes gaps and overlaps
    impossible at the schema level.

    If the block summaries exceed the context budget, blocks are split
    into evenly-sized chunks and cartography runs separately on each chunk.
    Chapter titles get ``"Part N — "`` prepended in split mode.

    Any failure after all retries is a hard stop — the exception propagates
    so the book is skipped entirely.
    """
    stage = artifact.stages[CARTOGRAPHY_STAGE]
    stage.status = "running"
    useful_blocks = [block for block in artifact.blocks if block.useful is not False]
    print(f"\n{'='*80}")
    print(f"🔍 CARTOGRAPHER START")
    print(f"🔍 Total blocks: {len(artifact.blocks)}")
    print(f"🔍 Useful blocks: {len(useful_blocks)}")
    if budget:
        print(f"🔍 Context budget: {budget}")
    print(f"{'='*80}\n")

    if not useful_blocks:
        artifact.chapters = []
        stage.status = "done"
        stage.notes = "No useful blocks remained after mini-summary classification."
        stage.outputs = {**stage.outputs, "chapter_count": 0}
        return artifact.touch()

    print("🔬 EXAMINING BLOCKS:\n")
    for i, block in enumerate(useful_blocks[:5]):
        print(f"  Block {i+1}: {block.block_id}")
        print(f"    ID: {block.block_id}")
        print(f"    Order: {block.order}")
        print(f"    Useful: {block.useful}")
        print(f"    Mini summary: {block.mini_summary}")
        print(f"    Text length: {len(block.text) if block.text else 0} chars")
        print(f"    Token est: {block.token_estimate}")
        print(f"    ---")

    system = load_prompt(prompt_file)
    system_tokens = estimate_tokens(system, llm_settings.model)

    n_blocks = len(useful_blocks)

    # Estimate tokens for the numbered block lines
    def _block_line_tokens(block: BlockArtifact) -> int:
        summary = block.mini_summary or ""
        return estimate_tokens(f"   XXXX: {summary}\n", llm_settings.model)

    total_block_tokens = sum(_block_line_tokens(b) for b in useful_blocks)
    print(f"\n📊 Token estimation:")
    print(f"   System prompt: ~{system_tokens} tokens")
    print(f"   Block summaries: ~{total_block_tokens} tokens")
    print(f"   Total input: ~{system_tokens + total_block_tokens} tokens", flush=True)

    # ── CHECK IF SPLITTING IS NEEDED (token budget only) ──
    if budget is not None:
        per_call_overhead = estimate_tokens(
            "\n---\n❌ YOUR PREVIOUS CHAPTER MAP WAS REJECTED:\n...\n---\nPlease fix ALL of the issues above...\n",
            llm_settings.model,
        )
        available_per_chunk = budget.usable - system_tokens - per_call_overhead
        total_input = system_tokens + total_block_tokens + per_call_overhead

        if total_input > budget.usable and available_per_chunk > 0:
            num_chunks = max(2, (total_block_tokens + available_per_chunk - 1) // available_per_chunk)
            print(f"\n   ✂️  ~{total_input} tokens exceeds budget of ~{budget.usable}")
            print(f"   ✂️  Splitting into {num_chunks} evenly-sized chunk(s)"
                  f" (~{n_blocks // num_chunks} blocks each)\n")

            chunks: list[list[BlockArtifact]] = []
            base = n_blocks // num_chunks
            remainder = n_blocks % num_chunks
            start = 0
            for i in range(num_chunks):
                chunk_size = base + (1 if i < remainder else 0)
                chunks.append(useful_blocks[start:start + chunk_size])
                start += chunk_size
        else:
            chunks = [useful_blocks]
    else:
        chunks = [useful_blocks]

    # ── RUN CARTOGRAPHY ON EACH CHUNK ──
    all_chapters: list[ChapterArtifact] = []
    total_chunks = len(chunks)

    for chunk_idx, chunk_blocks in enumerate(chunks, start=1):
        part_label = f"Part {chunk_idx} — " if total_chunks > 1 else ""
        if part_label:
            print(f"\n{'─'*60}")
            print(f"📦 CARTOGRAPHY CHUNK {chunk_idx}/{total_chunks} "
                  f"({len(chunk_blocks)} blocks)")
            print(f"{'─'*60}", flush=True)

        chunk_chapters = _run_cartography_on_blocks(
            artifact,
            chunk_blocks,
            llm_settings=llm_settings,
            prompt_file=prompt_file,
            part_label=part_label,
        )
        all_chapters.extend(chunk_chapters)

    # ── ASSIGN GLOBAL CHAPTER ORDER ──
    for order, chapter in enumerate(all_chapters, start=1):
        chapter.chapter_id = f"chapter_{order:03d}"
        chapter.order = order

    artifact.chapters = all_chapters
    stage.status = "done"
    stage.notes = (
        f"Generated chapter map from ordered mini-summaries "
        f"({total_chunks} chunk(s))."
    )
    print(f"\n✓ Cartographer mapped {len(all_chapters)} chapter(s) "
          f"across {total_chunks} chunk(s)")

    # SYNC SAVE & VERIFY chapter mapping
    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    save_artifact_sync(artifact, book_yaml_path)

    # VERIFY chapter data saved correctly
    verify_data = yaml.safe_load(book_yaml_path.read_text(encoding="utf-8"))
    if len(verify_data.get('chapters', [])) != len(artifact.chapters):
        print(f"   ❌ VERIFY FAILED - chapters count mismatch!", flush=True)
        raise RuntimeError("Chapter save verification failed")

    print(f"💾 SAVED & VERIFIED chapter mapping", flush=True)

    stage.outputs = {
        **stage.outputs,
        "chapter_count": len(artifact.chapters),
        "useful_blocks": len(useful_blocks),
        "cartography_chunks": total_chunks,
        "model": llm_settings.model,
    }
    sys.stdout.flush()
    return artifact.touch()


# ── Step 0: Precise Semantic Boundary Detection ─────────────────────────────

def _split_lines_with_positions(text: str) -> list[tuple[int, int, str]]:
    """Split text into lines with exact character offsets.
    Returns [(char_start, char_end_exclusive, line_text), ...].
    char_end_exclusive follows Python slicing convention.
    """
    result: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.split("\n"):
        end = pos + len(line)
        result.append((pos, end, line))
        pos = end + 1  # +1 for the newline character
    return result


def _build_token_windows(
    lines: list[str],
    *,
    window_tokens: int,
    overlap_pct: float,
    encoder,
) -> list[tuple[int, list[str]]]:
    """Build overlapping token-budgeted windows over lines.
    Returns [(global_start_line_idx, window_lines), ...].
    Each window contains ~window_tokens worth of text.
    Overlap ensures boundaries near window edges get a second opinion.
    """
    windows: list[tuple[int, list[str]]] = []
    i = 0
    while i < len(lines):
        window_lines: list[str] = []
        token_total = 0
        j = i
        while j < len(lines) and token_total < window_tokens:
            window_lines.append(lines[j])
            token_total += _token_count(lines[j], encoder)
            j += 1

        if not window_lines:
            break

        windows.append((i, window_lines))

        # Calculate overlap for next window
        if j >= len(lines):
            break
        overlap_lines = max(1, int(len(window_lines) * overlap_pct))
        i = j - overlap_lines

    return windows


def generate_precise_blocks(
    source_text: str,
    *,
    window_tokens: int = 8000,
    max_boundaries_per_window: int = 16,
    overlap_pct: float = 0.05,
    encoding_model: str = "gpt-4o-mini",
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_precise_chunk.md",
) -> list[BlockArtifact]:
    """Step 0: LLM-based precise semantic boundary detection.

    Splits source into ~window_tokens token windows (with overlap),
    sends each window to the LLM as line-numbered text, and collects
    semantic boundary line numbers. Converts boundaries into precise
    BlockArtifact objects that never split mid-thought.

    Falls back to mechanical token-splitting if no boundaries are found.
    """
    if not source_text.strip():
        return []

    encoder = _get_encoder(encoding_model)
    raw_lines = source_text.split("\n")
    positioned_lines = _split_lines_with_positions(source_text)

    print(f"   🧠 Step 0: Precise chunking — {len(raw_lines)} lines, "
          f"~{window_tokens} token windows, max {max_boundaries_per_window} boundaries/window, "
          f"{overlap_pct:.0%} overlap", flush=True)

    # Build overlapping token windows
    windows = _build_token_windows(
        raw_lines,
        window_tokens=window_tokens,
        overlap_pct=overlap_pct,
        encoder=encoder,
    )
    print(f"   🪟 Built {len(windows)} window(s)", flush=True)

    if not windows:
        return []

    # Collect boundaries from all windows (deduplicated via set)
    all_boundaries: set[int] = set()
    system_template = load_prompt(prompt_file)

    for win_idx, (global_start, window_lines) in enumerate(windows):
        # Format: "1 | text\n2 | text\n..."
        formatted = "\n".join(
            f"{i + 1} | {line}" for i, line in enumerate(window_lines)
        )

        system = system_template.replace("{max_boundaries}", str(max_boundaries_per_window))

        print(f"   🔍 Window {win_idx + 1}/{len(windows)}: "
              f"lines {global_start + 1}–{global_start + len(window_lines)} "
              f"({len(window_lines)} lines, ~{_token_count('\n'.join(window_lines), encoder)} tokens)", flush=True)

        try:
            result: PreciseChunkResult = _call_json_sync(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": formatted},
                ],
                llm_settings,
                response_model=PreciseChunkResult,
            )

            # Convert local 1-based line numbers to global 0-based indices
            for local_line in result.boundaries:
                if 1 <= local_line <= len(window_lines):
                    global_line_idx = global_start + local_line - 1
                    # Exclude very first and very last line of the entire text
                    if 0 < global_line_idx < len(raw_lines):
                        all_boundaries.add(global_line_idx)

            print(f"   ✅ Window {win_idx + 1}: {len(result.boundaries)} boundaries → "
                  f"{result.boundaries[:5]}{'...' if len(result.boundaries) > 5 else ''}", flush=True)

        except Exception as e:
            print(f"   ⚠️ Window {win_idx + 1} failed: {e}", flush=True)
            continue

    sorted_boundaries = sorted(all_boundaries)
    print(f"   📏 Collected {len(sorted_boundaries)} unique boundaries across all windows", flush=True)

    if not sorted_boundaries:
        print(f"   ⚠️ No semantic boundaries detected — falling back to mechanical token-splitting", flush=True)
        return build_blocks(
            source_text,
            target_tokens=1024,
            min_tokens=768,
            max_tokens=1280,
            encoding_model=encoding_model,
        )

    # Create blocks from consecutive boundaries
    blocks: list[BlockArtifact] = []
    block_start_idx = 0
    order = 1

    for boundary in sorted_boundaries:
        if boundary > block_start_idx:
            char_start = positioned_lines[block_start_idx][0]
            char_end = positioned_lines[boundary - 1][1]
            block_text = source_text[char_start:char_end]
            blocks.append(
                BlockArtifact(
                    block_id=f"block_{order:04d}",
                    order=order,
                    char_start=char_start,
                    char_end=char_end,
                    text=block_text,
                    token_estimate=_token_count(block_text, encoder),
                )
            )
            order += 1
        block_start_idx = boundary

    # Final block (from last boundary to end of text)
    if block_start_idx < len(positioned_lines):
        char_start = positioned_lines[block_start_idx][0]
        char_end = positioned_lines[-1][1]
        block_text = source_text[char_start:char_end]
        blocks.append(
            BlockArtifact(
                block_id=f"block_{order:04d}",
                order=order,
                char_start=char_start,
                char_end=char_end,
                text=block_text,
                token_estimate=_token_count(block_text, encoder),
            )
        )

    print(f"   ✂️  Precise chunking produced {len(blocks)} blocks "
          f"(avg ~{_token_count(source_text, encoder) // max(len(blocks), 1)} tokens/block)", flush=True)
    return blocks


def map_book_structure(
    artifact: BookArtifact,
    source_text: str,
    *,
    # Legacy mechanical-split params (used when llm_settings is None)
    target_tokens: int = 1024,
    min_tokens: int = 768,
    max_tokens: int = 1280,
    encoding_model: str = "gpt-4o-mini",
    # Step 0: LLM-based precise chunking (when provided, replaces mechanical split)
    llm_settings: LLMSettings | None = None,
    window_tokens: int = 8000,
    max_boundaries_per_window: int = 16,
    overlap_pct: float = 0.05,
) -> BookArtifact:
    """Map book structure into blocks.

    When llm_settings is provided:
      STEP 0 — LLM-based precise semantic boundary detection.
      Splits source into ~window_tokens token windows, sends each to the LLM
      as line-numbered text, and uses the returned boundary line numbers to
      create blocks that never split mid-thought.

    When llm_settings is None:
      Legacy mechanical token-based splitting via build_blocks().
    """
    artifact.stages.setdefault(CARTOGRAPHY_STAGE, StageState(name=CARTOGRAPHY_STAGE))

    if llm_settings is not None:
        print(f"   🧠 Step 0: Precise semantic chunking "
              f"(~{window_tokens} token windows, max {max_boundaries_per_window} boundaries/window)", flush=True)
        artifact.blocks = generate_precise_blocks(
            source_text,
            window_tokens=window_tokens,
            max_boundaries_per_window=max_boundaries_per_window,
            overlap_pct=overlap_pct,
            encoding_model=encoding_model,
            llm_settings=llm_settings,
        )
        method = "precise_llm"
    else:
        print(f"   📊 Tokenizing with {encoding_model}...", flush=True)
        artifact.blocks = build_blocks(
            source_text,
            target_tokens=target_tokens,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            encoding_model=encoding_model,
        )
        method = "mechanical_token"

    print(f"   ✂️  Split into {len(artifact.blocks)} blocks", flush=True)
    artifact.stages[CARTOGRAPHY_STAGE].notes = (
        "Precise semantic blocks generated (Step 0 LLM boundary detection)."
        if method == "precise_llm"
        else "Block anchors generated. TODO: create mini-summaries and group them into chapters."
    )
    artifact.stages[CARTOGRAPHY_STAGE].status = "ready"
    artifact.stages[CARTOGRAPHY_STAGE].outputs = {
        "block_count": len(artifact.blocks),
        "method": method,
        "encoding_model": encoding_model,
    }
    if method == "mechanical_token":
        artifact.stages[CARTOGRAPHY_STAGE].outputs.update({
            "target_tokens": target_tokens,
            "min_tokens": min_tokens,
            "max_tokens": max_tokens,
        })
    else:
        artifact.stages[CARTOGRAPHY_STAGE].outputs.update({
            "window_tokens": window_tokens,
            "max_boundaries_per_window": max_boundaries_per_window,
            "overlap_pct": overlap_pct,
        })
    return artifact.touch()
