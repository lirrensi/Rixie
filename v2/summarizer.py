# FILE: v2/summarizer.py
# PURPOSE: Generate chapter-level summaries and a top abstract for the V2 artifact.
# OWNS: Separate short/detailed chapter summarization and abstract synthesis stage.
# EXPORTS: summarize_chapters, synthesize_overview.
# DOCS: v2/process.py, v2/schema.py
#
# POLICY: If data exists on disk, skip it. Never redo a successful LLM call.
# The only check is: is the field not None? → skip. Same as blocks.

from __future__ import annotations

from pathlib import Path

from v2.budget import ContextBudget, estimate_tokens
from v2.cartographer import LLMSettings
from v2.checkpoint import CheckpointTracker, save_artifact_sync
from v2.pipeline import completion_with_retry
from v2.prompts import load_prompt
from v2.schema import BookArtifact, StageState

CHAPTER_SUMMARIES_STAGE = "chapter_summaries"
OVERVIEW_STAGE = "overview"


def _call_text_sync(messages: list[dict], settings: LLMSettings) -> str:
    """Text completion via OpenAI SDK - no LiteLLM."""
    return completion_with_retry(settings, messages)


def _chapter_source_text(artifact: BookArtifact, block_ids: list[str]) -> str:
    block_map = {block.block_id: block for block in artifact.blocks}
    parts = []
    for block_id in block_ids:
        block = block_map.get(block_id)
        if block and block.text:
            parts.append(block.text)
    return "\n\n".join(parts).strip()


def _summarize_short_sync(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str:
    """Generate short chapter summary. Raises on failure (no fallback)."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    return _call_text_sync(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        settings,
    )


def _summarize_detailed_sync(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str:
    """Generate detailed chapter summary. Raises on failure (no fallback)."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    return _call_text_sync(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        settings,
    )


def _split_chapter_blocks_by_budget(
    artifact: BookArtifact,
    chapter,
    *,
    budget: ContextBudget | None,
    settings: LLMSettings,
    prompt_file: str,
) -> list[tuple[str, list[str]]]:
    """Split chapter blocks into parts if they exceed the context budget.
    
    Returns list of (title_suffix, block_ids) tuples.
    If no split needed, returns [(chapter.title, chapter.blocks)].
    """
    if budget is None:
        return [(chapter.title, chapter.blocks)]

    system_prompt = ""
    try:
        system_prompt = load_prompt(prompt_file)
    except Exception:
        pass

    system_tokens = estimate_tokens(system_prompt, settings.model)
    available = budget.usable - system_tokens

    # Estimate total chapter text tokens
    block_map = {b.block_id: b for b in artifact.blocks}
    total_tokens = 0
    for block_id in chapter.blocks:
        block = block_map.get(block_id)
        if block and block.text:
            total_tokens += estimate_tokens(block.text, settings.model)

    if total_tokens <= available:
        return [(chapter.title, chapter.blocks)]

    # Need to split — distribute blocks evenly into parts
    num_blocks = len(chapter.blocks)
    # Estimate how many parts: each part should fit in budget
    avg_block_tokens = total_tokens / num_blocks if num_blocks > 0 else 1
    blocks_per_part = max(1, int(available / avg_block_tokens))
    num_parts = max(2, (num_blocks + blocks_per_part - 1) // blocks_per_part)

    # Evenly distribute blocks
    parts: list[list[str]] = []
    base = num_blocks // num_parts
    remainder = num_blocks % num_parts
    start = 0
    for i in range(num_parts):
        chunk_size = base + (1 if i < remainder else 0)
        parts.append(chapter.blocks[start:start + chunk_size])
        start += chunk_size

    result = []
    for i, part_blocks in enumerate(parts, start=1):
        suffix = f"Part {i}" if num_parts > 1 else ""
        result.append((suffix, part_blocks))

    print(f"   ✂️  Chapter '{chapter.title}' split into {num_parts} part(s) "
          f"({total_tokens} tokens exceeds {available} budget)", flush=True)

    return result


def _summarize_chapter_parts(
    artifact: BookArtifact,
    chapter,
    *,
    summarizer_fn,
    settings: LLMSettings,
    prompt_file: str,
    summary_type: str,
    budget: ContextBudget | None,
) -> str:
    """Generate a summary for a chapter, splitting into parts if needed.
    
    Args:
        summarizer_fn: Either _summarize_short_sync or _summarize_detailed_sync.
    """
    parts = _split_chapter_blocks_by_budget(
        artifact, chapter,
        budget=budget,
        settings=settings,
        prompt_file=prompt_file,
    )

    summaries: list[str] = []
    for suffix, block_ids in parts:
        part_text = _chapter_source_text(artifact, block_ids)
        part_title = f"{chapter.title} — {suffix}" if suffix else chapter.title
        print(f"   📤 {summary_type} sent: {part_title}", flush=True)
        summary = summarizer_fn(part_title, part_text, settings, prompt_file)
        summaries.append(summary)
        print(f"   ✅ {summary_type} done: {part_title}", flush=True)

    if len(summaries) == 1:
        return summaries[0]

    # Combine multi-part summaries with a clear divider
    combined = []
    for i, s in enumerate(summaries, start=1):
        combined.append(f"[Part {i}]\n{s}")
    return "\n\n---\n\n".join(combined)


def summarize_chapters(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    short_settings: LLMSettings,
    detailed_settings: LLMSettings,
    parallel_calls: int = 1,  # IGNORED - always sequential
    short_prompt_file: str = "prompt_chapter_short.md",
    detailed_prompt_file: str = "prompt_chapter_detailed.md",
    checkpoint_pct: float = 5.0,
    budget: ContextBudget | None = None,
) -> BookArtifact:
    artifact.stages.setdefault(CHAPTER_SUMMARIES_STAGE, StageState(name=CHAPTER_SUMMARIES_STAGE))
    stage = artifact.stages[CHAPTER_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating separate short and detailed summaries for each mapped chapter."

    chapter_count = len(artifact.chapters)
    total = chapter_count
    print(f"   ✍️  Chapter summaries: {total} chapter(s) - SEQUENTIAL", flush=True)

    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml

    # ---- SHORT SUMMARIES ----
    short_pending = [
        idx for idx, ch in enumerate(artifact.chapters)
        if ch.short_summary is None
    ]
    print(f"   short_summary: {total - len(short_pending)}/{total} already done, {len(short_pending)} pending", flush=True)

    if short_pending:
        short_ck = CheckpointTracker(len(short_pending), every_pct=checkpoint_pct)
        for idx in short_pending:
            chapter = artifact.chapters[idx]
            artifact.chapters[idx].short_summary = _summarize_chapter_parts(
                artifact, chapter,
                summarizer_fn=_summarize_short_sync,
                settings=short_settings,
                prompt_file=short_prompt_file,
                summary_type="Short",
                budget=budget,
            )
            if short_ck.should_save():
                save_artifact_sync(artifact, book_yaml_path)
                print(f"   💾 Checkpoint save short: {short_ck.progress_pct:.0f}%", flush=True)

        save_artifact_sync(artifact, book_yaml_path)
        print(f"   💾 Short summaries final save complete", flush=True)
    else:
        print(f"   ✓ All short summaries already present", flush=True)

    # ---- DETAILED SUMMARIES ----
    detailed_pending = [
        idx for idx, ch in enumerate(artifact.chapters)
        if ch.detailed_summary is None
    ]
    print(f"   detailed_summary: {total - len(detailed_pending)}/{total} already done, {len(detailed_pending)} pending", flush=True)

    if detailed_pending:
        detailed_ck = CheckpointTracker(len(detailed_pending), every_pct=checkpoint_pct)
        for idx in detailed_pending:
            chapter = artifact.chapters[idx]
            artifact.chapters[idx].detailed_summary = _summarize_chapter_parts(
                artifact, chapter,
                summarizer_fn=_summarize_detailed_sync,
                settings=detailed_settings,
                prompt_file=detailed_prompt_file,
                summary_type="Detail",
                budget=budget,
            )
            if detailed_ck.should_save():
                save_artifact_sync(artifact, book_yaml_path)
                print(f"   💾 Checkpoint save detailed: {detailed_ck.progress_pct:.0f}%", flush=True)

        save_artifact_sync(artifact, book_yaml_path)
        print(f"   💾 Detailed summaries final save complete", flush=True)
    else:
        print(f"   ✓ All detailed summaries already present", flush=True)

    # ---- REPORT ----
    stage.status = "done"
    stage.notes = "All chapter summaries generated successfully."
    print(f"   ✅ Chapter summaries complete: {total} chapters", flush=True)

    stage.outputs = {
        "chapter_count": chapter_count,
        "parallel_calls": 1,
        "short_model": short_settings.model,
        "detailed_model": detailed_settings.model,
    }
    return artifact.touch()


def synthesize_overview(
    artifact: BookArtifact,
    workspace_dir: Path | None = None,
    *,
    ultra_dense_settings: LLMSettings,
    prompt_file: str = "prompt_ultra_dense.md",
    budget: ContextBudget | None = None,
) -> BookArtifact:
    artifact.stages.setdefault(OVERVIEW_STAGE, StageState(name=OVERVIEW_STAGE))
    stage = artifact.stages[OVERVIEW_STAGE]

    # Already done? Skip entirely.
    if artifact.overview.ultra_dense_summary is not None:
        print("   ✓ Abstract already present — skipping", flush=True)
        stage.status = "done"
        stage.notes = "Abstract already present."
        return artifact.touch()

    stage.status = "running"
    stage.notes = "Building a top abstract from chapter short summaries."

    # Check we have short summaries to work with
    available = [c for c in artifact.chapters if c.short_summary]
    if not available:
        stage.status = "failed"
        stage.notes = "No chapter short summaries available; cannot synthesize overview."
        print("   ⚠️ No short summaries available — skipping overview synthesis.", flush=True)
        return artifact.touch()

    print(f"   🧪 Abstract: compressing {len(available)} chapter short summary(s)", flush=True)

    print("   📝 Merging chapter summaries...", flush=True)

    # Build the combined summary text
    chapter_summaries = "\n\n".join(
        f"## {chapter.title}\n{chapter.short_summary or ''}" for chapter in artifact.chapters
    ).strip()
    print(f"   📋 Combined text: {len(chapter_summaries):,} chars", flush=True)

    system = load_prompt(prompt_file)

    # ── Check if splitting is needed ──
    if budget is not None:
        system_tokens = estimate_tokens(system, ultra_dense_settings.model)
        summaries_tokens = estimate_tokens(chapter_summaries, ultra_dense_settings.model)
        total_tokens = system_tokens + summaries_tokens

        if total_tokens > budget.usable:
            # Split chapters into groups
            num_chapters = len(artifact.chapters)

            # Estimate how many chapters per group
            available_per_group = budget.usable - system_tokens
            avg_chapter_tokens = summaries_tokens / num_chapters if num_chapters > 0 else 1
            chapters_per_group = max(1, int(available_per_group / avg_chapter_tokens))
            num_groups = max(2, (num_chapters + chapters_per_group - 1) // chapters_per_group)

            # Evenly distribute chapters
            groups: list[list] = []
            base = num_chapters // num_groups
            remainder = num_chapters % num_groups
            start = 0
            for i in range(num_groups):
                chunk_size = base + (1 if i < remainder else 0)
                groups.append(artifact.chapters[start:start + chunk_size])
                start += chunk_size

            print(f"   ✂️  Abstract split into {num_groups} group(s) "
                  f"({total_tokens} tokens exceeds {budget.usable} budget)", flush=True)

            group_abstracts: list[str] = []
            for group_idx, group in enumerate(groups, start=1):
                group_text = "\n\n".join(
                    f"## {ch.title}\n{ch.short_summary or ''}" for ch in group
                ).strip()
                group_title = f"Part {group_idx}"
                print(f"   🤖 Calling {ultra_dense_settings.model} for abstract ({group_title})...", flush=True)

                result = _call_text_sync(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": group_text},
                    ],
                    ultra_dense_settings,
                )
                if not result:
                    raise RuntimeError(
                        f"Abstract call for {group_title} returned empty response."
                    )
                group_abstracts.append(result)

            # Combine group abstracts into final overview
            combined = []
            for i, ab in enumerate(group_abstracts, start=1):
                combined.append(f"[Part {i}]\n{ab}")
            artifact.overview.ultra_dense_summary = "\n\n---\n\n".join(combined)
        else:
            # Single call — fits in budget
            print(f"   🤖 Calling {ultra_dense_settings.model} for abstract...", flush=True)
            result = _call_text_sync(
                [{"role": "system", "content": system}, {"role": "user", "content": chapter_summaries}],
                ultra_dense_settings,
            )
            if not result:
                raise RuntimeError("Abstract call returned empty response — cannot produce final output.")
            artifact.overview.ultra_dense_summary = result
    else:
        # No budget — single call (legacy behavior)
        print(f"   🤖 Calling {ultra_dense_settings.model} for abstract...", flush=True)
        result = _call_text_sync(
            [{"role": "system", "content": system}, {"role": "user", "content": chapter_summaries}],
            ultra_dense_settings,
        )
        if not result:
            raise RuntimeError("Abstract call returned empty response — cannot produce final output.")
        artifact.overview.ultra_dense_summary = result

    # Save immediately
    if workspace_dir:
        book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
        save_artifact_sync(artifact, book_yaml_path)
        print(f"   💾 Abstract saved", flush=True)

    stage.status = "done"
    stage.notes = "Abstract generated successfully."
    print("   ✅ Abstract complete", flush=True)

    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "ultra_dense_model": ultra_dense_settings.model,
    }
    return artifact.touch()