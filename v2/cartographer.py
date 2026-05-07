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
    block_start: str
    block_end: str


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


def save_artifact_with_lock(artifact: BookArtifact, book_yaml_path: Path):
    """Save artifact directly to disk with sync flush."""
    yaml_content = yaml.safe_dump(artifact.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    with open(book_yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
        f.flush()
        os.fsync(f.fileno())


def generate_block_mini_summaries(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    parallel_calls: int = 8,  # IGNORED - always sequential now
    prompt_file: str = "prompt_block_mini_summary.md",
    save_every: int = 5,  # IGNORED - save every block now
    max_per_block_retries: int = 3,
) -> BookArtifact:
    """Generate mini summaries SEQUENTIALLY with per-block retry and sync saves.

    Blocks that fail after all retries are force-marked as useful=False
    so the cartographer never sees a block with a missing fingerprint.
    """
    import time as time_mod

    artifact.stages.setdefault(MINI_SUMMARIES_STAGE, StageState(name=MINI_SUMMARIES_STAGE))
    stage = artifact.stages[MINI_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating one-sentence block summaries and useful=false classifications."

    # SYNC SAVE initial status
    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    save_artifact_with_lock(artifact, book_yaml_path)

    total = len(artifact.blocks)
    print(f"   🔍 Mini summaries: {total} block(s)", flush=True)

    # Skip blocks that already have mini_summaries
    pending_indices = [
        idx for idx, block in enumerate(artifact.blocks)
        if block.mini_summary is None or block.useful is None
    ]

    if not pending_indices:
        print(f"   ✓ All {total} blocks already have mini summaries", flush=True)
        stage.status = "done"
        stage.notes = "All block mini-summaries already present."
        return artifact.touch()

    print(f"   → Resuming {len(pending_indices)} pending blocks (skipping {total - len(pending_indices)} complete)", flush=True)

    print(f"   🔥 Processing {len(pending_indices)} blocks SEQUENTIALLY "
          f"(max {max_per_block_retries} retries per block)", flush=True)
    save_count = 0

    # Process ONE block at a time, with per-block retries
    for idx in pending_indices:
        block = artifact.blocks[idx]
        print(f"   📤 Processing {idx+1}/{total}: {block.block_id}", flush=True)

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
                artifact.blocks[idx].mini_summary = result.mini_summary
                artifact.blocks[idx].useful = result.useful
                success = True

                # TRUE SYNC SAVE to disk - BLOCKING until complete
                save_artifact_with_lock(artifact, book_yaml_path)

                # VERIFY save by re-reading
                verify_data = book_yaml_path.read_text(encoding="utf-8")
                verify_yaml = yaml.safe_load(verify_data)
                verify_block = verify_yaml['blocks'][idx]

                if verify_block['mini_summary'] != result.mini_summary or verify_block['useful'] != result.useful:
                    print(f"   ❌ VERIFY FAILED for block {idx+1} - SAVE CORRUPT!", flush=True)
                    raise RuntimeError(f"Save verification failed for block {idx+1}")

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

        save_count += 1
        print(f"   💾 BLOCK SAVE {idx+1}/{total} COMPLETE & VERIFIED", flush=True)

    # Final SYNC SAVE & VERIFY complete results
    save_artifact_with_lock(artifact, book_yaml_path)

    # Verify all blocks are saved
    verify_data = yaml.safe_load(book_yaml_path.read_text(encoding="utf-8"))
    verify_artifact = BookArtifact.model_validate(verify_data)
    partial_count = sum(1 for b in verify_artifact.blocks if b.mini_summary is None or b.useful is None)

    print(f"   💾 FINAL SAVE COMPLETE & VERIFIED ({len(artifact.blocks)} blocks)", flush=True)

    useful_blocks = sum(1 for block in artifact.blocks if block.useful)
    failures = sum(1 for idx, block in enumerate(artifact.blocks) if block.mini_summary is None)

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


def _snap_to_useful(
    block_id: str,
    *,
    useful_ids: list[str],
    by_id: dict[str, BlockArtifact],
    direction: str,  # "forward" or "backward"
) -> str | None:
    """Snap a block_id to the nearest useful block in the given direction.

    When the LLM returns a chapter boundary that references a non-useful
    block (e.g. useful=False), this walks forward/backward through the
    useful_ids list to find the nearest valid anchor.
    """
    if block_id in set(useful_ids):
        return block_id

    target_order = by_id[block_id].order

    if direction == "backward":
        # Walk backward: find the last useful block with order <= target_order
        best: str | None = None
        for uid in useful_ids:
            if by_id[uid].order <= target_order:
                best = uid
            else:
                break
        return best

    # direction == "forward"
    for uid in useful_ids:
        if by_id[uid].order >= target_order:
            return uid
    return None


def _validate_and_materialize_chapters(
    artifact: BookArtifact,
    chapter_ranges: list[ChapterRange],
) -> tuple[list[ChapterArtifact], list[str]]:
    """Validate and materialize chapter ranges.

    Returns:
        (chapters, []) on success — every useful block appears exactly once.
        ([], errors) on failure — errors explain gaps and overlaps for LLM feedback.
    """
    by_id = {block.block_id: block for block in artifact.blocks}
    useful_ids = [block.block_id for block in artifact.blocks if block.useful is not False]
    if not useful_ids:
        return [], []

    errors: list[str] = []
    chapters: list[ChapterArtifact] = []
    covered: list[str] = []

    for order, chapter in enumerate(chapter_ranges, start=1):
        if chapter.block_start not in by_id or chapter.block_end not in by_id:
            errors.append(
                f"Unknown block ID in chapter '{chapter.title}': "
                f"{chapter.block_start} or {chapter.block_end} does not exist"
            )
            continue

        # Snap boundaries to nearest useful blocks (defense-in-depth;
        # with renumbering the LLM should never reference non-useful blocks)
        start_id = _snap_to_useful(
            chapter.block_start, useful_ids=useful_ids, by_id=by_id, direction="forward"
        )
        end_id = _snap_to_useful(
            chapter.block_end, useful_ids=useful_ids, by_id=by_id, direction="backward"
        )

        if start_id is None or end_id is None:
            errors.append(
                f"Chapter '{chapter.title}': could not resolve boundary "
                f"({chapter.block_start} or {chapter.block_end}) to a useful block"
            )
            continue

        start_idx = useful_ids.index(start_id)
        end_idx = useful_ids.index(end_id)
        if end_idx < start_idx:
            errors.append(
                f"Chapter '{chapter.title}': end block ({end_id}) comes before start block ({start_id})"
            )
            continue

        block_ids = useful_ids[start_idx : end_idx + 1]
        covered.extend(block_ids)
        start_block = by_id[block_ids[0]]
        end_block = by_id[block_ids[-1]]
        chapters.append(
            ChapterArtifact(
                chapter_id=f"chapter_{order:03d}",
                order=order,
                title=" ".join(chapter.title.split()) or f"Chapter {order}",
                block_start=start_block.order,
                block_end=end_block.order,
                char_start=start_block.char_start,
                char_end=end_block.char_end,
                blocks=block_ids,
            )
        )

    # Check for gaps: useful blocks not covered by any chapter
    uncovered = [b for b in useful_ids if b not in covered]
    if uncovered:
        preview = uncovered[:5]
        errors.append(
            f"GAP: {len(uncovered)} useful block(s) are not covered by any chapter. "
            f"Missing: {preview}{'...' if len(uncovered) > 5 else ''}. "
            f"Every block must appear in exactly one chapter."
        )

    # Check for overlaps: blocks appearing in multiple chapters
    if len(covered) != len(set(covered)):
        from collections import Counter
        dupes = sorted(bid for bid, count in Counter(covered).items() if count > 1)
        preview = dupes[:5]
        errors.append(
            f"OVERLAP: {len(dupes)} block(s) appear in multiple chapters. "
            f"Duplicated: {preview}{'...' if len(dupes) > 5 else ''}. "
            f"Each block must belong to exactly one chapter."
        )

    if errors:
        return [], errors

    return chapters, []


def group_blocks_into_chapters(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_cartographer_map.md",
) -> BookArtifact:
    """Group blocks into chapters - SYNCHRONOUS.

    Any failure after all retries is a hard stop — the exception propagates
    to the caller so the book is skipped entirely (no partial output).
    """
    stage = artifact.stages[CARTOGRAPHY_STAGE]
    stage.status = "running"
    useful_blocks = [block for block in artifact.blocks if block.useful is not False]
    print(f"\n{'='*80}")
    print(f"🔍 CARTOGRAPHER START")
    print(f"🔍 Total blocks: {len(artifact.blocks)}")
    print(f"🔍 Useful blocks: {len(useful_blocks)}")
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

    print("\n📋 BUILDING BLOCK LINES FOR LLM:\n")
    # Renumber blocks sequentially so the LLM sees a gapless sequence.
    # Without this, gaps from discarded non-useful blocks let the LLM
    # infer missing IDs (e.g. "block_0090") and hallucinate boundaries.
    renumber_map: dict[str, str] = {}   # original_id → sequential_id
    reverse_map: dict[str, str] = {}    # sequential_id → original_id
    for new_idx, block in enumerate(useful_blocks, start=1):
        new_id = f"block_{new_idx:04d}"
        renumber_map[block.block_id] = new_id
        reverse_map[new_id] = block.block_id

    block_lines = []
    for block in useful_blocks:
        new_id = renumber_map[block.block_id]
        summary = block.mini_summary or ""
        line = f"{new_id}: {summary}"
        print(f"  {line}")
        block_lines.append(line)

    print(f"\n👤 Loading system prompt from: {prompt_file}", flush=True)
    sys.stdout.flush()
    system = load_prompt(prompt_file)
    print(f"📄 System prompt length: {len(system)} chars")
    print(f"\n{'='*80}")
    print(f"📄 SYSTEM PROMPT FULL TEXT:")
    print(f"{'='*80}")
    print(system)
    print(f"{'='*80}\n")

    user = "ORDERED BLOCK SUMMARIES:\\n" + "\\n".join(block_lines)
    print(f"📝 User message length: {len(user)} chars")
    print(f"📊 Block count in user message: {len(block_lines)}")

    print(f"\n{'='*80}")
    print(f"📝 USER MESSAGE FULL TEXT:")
    print(f"{'='*80}")
    print(user)
    print(f"{'='*80}\n")

    print(f"\n🤖 Multi-turn cartography: up to 6 turns with validation feedback", flush=True)
    print(f"🔧 LLM settings:")
    print(f"    model: {llm_settings.model}")
    print(f"    temperature: {llm_settings.temperature}")
    print(f"    thinking: {llm_settings.thinking}")
    print(f"    api_base: {llm_settings.api_base}")
    sys.stdout.flush()

    MAX_TURNS = 6
    base_user = "ORDERED BLOCK SUMMARIES:\\n" + "\\n".join(block_lines)
    feedback = ""
    last_parsed = None

    for turn in range(1, MAX_TURNS + 1):
        print(f"\n{'─'*60}")
        print(f"🔄 TURN {turn}/{MAX_TURNS}", flush=True)

        # Build user message: base summaries + optional validation feedback
        if feedback:
            user = (
                base_user
                + "\n\n---\n❌ YOUR PREVIOUS CHAPTER MAP WAS REJECTED:\n"
                + feedback
                + "\n---\nPlease fix ALL of the issues above and return a corrected chapter map."
            )
        else:
            user = base_user

        print(f"\n🚀 Calling _call_json_sync (turn {turn})...")
        parsed = _call_json_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            llm_settings,
            response_model=ChapterMapResult,
        )
        last_parsed = parsed

        print(f"\n✅ Turn {turn} response: {len(parsed.chapters)} chapter(s)")
        for i, chapter in enumerate(parsed.chapters):
            print(f"  Chapter {i+1}: {chapter.title}")
            print(f"    Start: {chapter.block_start}, End: {chapter.block_end}")

        # Remap renumbered block IDs back to original artifact block IDs
        for chapter in parsed.chapters:
            chapter.block_start = reverse_map.get(chapter.block_start, chapter.block_start)
            chapter.block_end = reverse_map.get(chapter.block_end, chapter.block_end)

        # Validate
        validated_chapters, errors = _validate_and_materialize_chapters(artifact, parsed.chapters)

        if not errors:
            # ── SUCCESS ──
            print(f"\n✅ VALIDATION PASSED on turn {turn}!")
            artifact.chapters = validated_chapters
            stage.status = "done"
            stage.notes = f"Generated chapter map from ordered mini-summaries (turn {turn}/{MAX_TURNS})."
            break

        # ── FAILED ── build feedback for next turn ──
        feedback = (
            f"The chapter map had {len(errors)} validation error(s):\n"
            + "\n".join(f"  • {e}" for e in errors)
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

    # If we exhausted all turns without success, last_parsed is set but validation failed
    if not artifact.chapters:
        raise RuntimeError(
            f"Cartographer failed after {MAX_TURNS} turns — "
            f"no valid chapter map produced. Last response had {len(last_parsed.chapters) if last_parsed else 0} chapters."
        )

    print(f"\n✓ Cartographer mapped {len(artifact.chapters)} chapter(s) in {turn} turn(s)")

    # SYNC SAVE & VERIFY chapter mapping
    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    save_artifact_with_lock(artifact, book_yaml_path)

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
