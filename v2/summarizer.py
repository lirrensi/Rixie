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
    # Skip chapters that already have a short_summary (not None)
    short_pending = [
        idx for idx, ch in enumerate(artifact.chapters)
        if ch.short_summary is None
    ]
    print(f"   short_summary: {total - len(short_pending)}/{total} already done, {len(short_pending)} pending", flush=True)

    if short_pending:
        short_ck = CheckpointTracker(len(short_pending), every_pct=checkpoint_pct)
        for idx in short_pending:
            chapter = artifact.chapters[idx]
            title = chapter.title
            text = _chapter_source_text(artifact, chapter.blocks)
            print(f"   📤 Short sent: {title}", flush=True)
            artifact.chapters[idx].short_summary = _summarize_short_sync(
                title, text, short_settings, short_prompt_file
            )
            if short_ck.should_save():
                save_artifact_sync(artifact, book_yaml_path)
                print(f"   💾 Checkpoint save short: {short_ck.progress_pct:.0f}%", flush=True)
            print(f"   ✅ Short done: {title}", flush=True)

        # Final anchor save
        save_artifact_sync(artifact, book_yaml_path)
        print(f"   💾 Short summaries final save complete", flush=True)
    else:
        print(f"   ✓ All short summaries already present", flush=True)

    # ---- DETAILED SUMMARIES ----
    # Skip chapters that already have a detailed_summary (not None)
    detailed_pending = [
        idx for idx, ch in enumerate(artifact.chapters)
        if ch.detailed_summary is None
    ]
    print(f"   detailed_summary: {total - len(detailed_pending)}/{total} already done, {len(detailed_pending)} pending", flush=True)

    if detailed_pending:
        detailed_ck = CheckpointTracker(len(detailed_pending), every_pct=checkpoint_pct)
        for idx in detailed_pending:
            chapter = artifact.chapters[idx]
            title = chapter.title
            text = _chapter_source_text(artifact, chapter.blocks)
            print(f"   📤 Detail sent: {title}", flush=True)
            artifact.chapters[idx].detailed_summary = _summarize_detailed_sync(
                title, text, detailed_settings, detailed_prompt_file
            )
            if detailed_ck.should_save():
                save_artifact_sync(artifact, book_yaml_path)
                print(f"   💾 Checkpoint save detailed: {detailed_ck.progress_pct:.0f}%", flush=True)
            print(f"   ✅ Detail done: {title}", flush=True)

        # Final anchor save
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
    chapter_summaries = "\n\n".join(
        f"## {chapter.title}\n{chapter.short_summary or ''}" for chapter in artifact.chapters
    ).strip()
    print(f"   📋 Combined text: {len(chapter_summaries):,} chars", flush=True)

    print(f"   🤖 Calling {ultra_dense_settings.model} for abstract...", flush=True)

    result = _call_text_sync(
        [
            {
                "role": "system",
                "content": load_prompt(prompt_file),
            },
            {"role": "user", "content": chapter_summaries},
        ],
        ultra_dense_settings,
    )
    if not result:
        raise RuntimeError("Abstract call returned empty response — cannot produce final output.")

    artifact.overview.ultra_dense_summary = result

    # Save immediately — one call, one save
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