# FILE: v2/summarizer.py
# PURPOSE: Generate chapter-level summaries and a top abstract for the V2 artifact.
# OWNS: Separate short/detailed chapter summarization and abstract synthesis stage.
# EXPORTS: summarize_chapters, synthesize_overview.
# DOCS: v2/process.py, v2/schema.py
#
# POLICY: Never write fallback garbage. If an AI call fails after all retries,
# the field stays None and the stage reports the failure.

from __future__ import annotations

import sys

from v2.cartographer import LLMSettings
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


def _summarize_short_sync(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str | None:
    """Returns None if summarization fails after all retries."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        return _call_text_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
    except Exception as e:
        print(f"   ❌ Short summary failed for '{chapter_title}': {e}", flush=True)
        return None


def _summarize_detailed_sync(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str | None:
    """Returns None if summarization fails after all retries."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        return _call_text_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
    except Exception as e:
        print(f"   ❌ Detailed summary failed for '{chapter_title}': {e}", flush=True)
        return None


def summarize_chapters(
    artifact: BookArtifact,
    *,
    short_settings: LLMSettings,
    detailed_settings: LLMSettings,
    parallel_calls: int = 1,  # IGNORED - always sequential
    short_prompt_file: str = "prompt_chapter_short.md",
    detailed_prompt_file: str = "prompt_chapter_detailed.md",
) -> BookArtifact:
    artifact.stages.setdefault(CHAPTER_SUMMARIES_STAGE, StageState(name=CHAPTER_SUMMARIES_STAGE))
    stage = artifact.stages[CHAPTER_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating separate short and detailed summaries for each mapped chapter."

    chapter_count = len(artifact.chapters)
    print(f"   ✍️ Chapter summaries: {chapter_count} chapter(s) - SEQUENTIAL", flush=True)

    chapter_payloads = [
        (idx, chapter.title, _chapter_source_text(artifact, chapter.blocks))
        for idx, chapter in enumerate(artifact.chapters)
    ]
    total = len(chapter_payloads)

    # ---- SHORT SUMMARIES ----
    short_failed = []
    for idx, title, text in chapter_payloads:
        print(f"   📤 Short sent: {title}", flush=True)
        result = _summarize_short_sync(title, text, short_settings, short_prompt_file)
        artifact.chapters[idx].short_summary = result
        if result:
            print(f"   ✅ Short done: {title}", flush=True)
        else:
            print(f"   ❌ Short FAILED: {title}", flush=True)
            short_failed.append(title)

    # ---- DETAILED SUMMARIES ----
    detail_failed = []
    for idx, title, text in chapter_payloads:
        print(f"   📤 Detail sent: {title}", flush=True)
        result = _summarize_detailed_sync(title, text, detailed_settings, detailed_prompt_file)
        artifact.chapters[idx].detailed_summary = result
        if result:
            print(f"   ✅ Detail done: {title}", flush=True)
        else:
            print(f"   ❌ Detail FAILED: {title}", flush=True)
            detail_failed.append(title)

    # ---- REPORT ----
    all_failed = set(short_failed + detail_failed)
    if all_failed:
        stage.status = "partial"
        failures = "; ".join(sorted(all_failed))
        stage.notes = f"Summaries generated with {len(all_failed)} failure(s): {failures}"
        print(f"   ⚠️ Chapter summaries: {total - len(short_failed)}/{total} short, "
              f"{total - len(detail_failed)}/{total} detailed OK. Failed: {failures}", flush=True)
    else:
        stage.status = "done"
        stage.notes = "All chapter summaries generated successfully."
        print(f"   ✅ Chapter summaries complete: {total} chapters", flush=True)

    stage.outputs = {
        "chapter_count": chapter_count,
        "parallel_calls": 1,
        "short_model": short_settings.model,
        "detailed_model": detailed_settings.model,
        "short_failures": short_failed,
        "detail_failures": detail_failed,
    }
    return artifact.touch()


def synthesize_overview(
    artifact: BookArtifact,
    *,
    ultra_dense_settings: LLMSettings,
    prompt_file: str = "prompt_ultra_dense.md",
) -> BookArtifact:
    artifact.stages.setdefault(OVERVIEW_STAGE, StageState(name=OVERVIEW_STAGE))
    stage = artifact.stages[OVERVIEW_STAGE]
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

    try:
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
        if result:
            artifact.overview.ultra_dense_summary = result
            stage.status = "done"
            stage.notes = "Abstract generated successfully."
            print("   ✅ Abstract complete", flush=True)
        else:
            stage.status = "failed"
            stage.notes = "Abstract call returned empty response."
            print("   ❌ Abstract returned empty — overview not written.", flush=True)
    except Exception as e:
        stage.status = "failed"
        stage.notes = f"Abstract call failed: {e}"
        print(f"   ❌ Abstract failed: {e}", flush=True)

    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "ultra_dense_model": ultra_dense_settings.model,
    }
    return artifact.touch()
