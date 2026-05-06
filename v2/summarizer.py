# FILE: v2/summarizer.py
# PURPOSE: Generate chapter-level summaries and a top abstract for the V2 artifact.
# OWNS: Separate short/detailed chapter summarization and abstract synthesis stage.
# EXPORTS: summarize_chapters, synthesize_overview.
# DOCS: v2/process.py, v2/schema.py
#
# POLICY: Never write fallback garbage. If an AI call fails after all retries,
# the field stays None and the stage reports the failure.

from __future__ import annotations

import asyncio
import sys

from v2.cartographer import LLMSettings
from v2.pipeline import acompletion_with_retry, build_completion_kwargs
from v2.prompts import load_prompt
from v2.schema import BookArtifact, StageState

CHAPTER_SUMMARIES_STAGE = "chapter_summaries"
OVERVIEW_STAGE = "overview"


async def _call_text_async(messages: list[dict], settings: LLMSettings) -> str:
    kwargs = build_completion_kwargs(
        settings.model,
        messages,
        temperature=settings.temperature,
        thinking=settings.thinking,
    )
    if settings.api_base:
        kwargs["api_base"] = settings.api_base
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.timeout:
        kwargs["timeout"] = settings.timeout
    return await acompletion_with_retry(kwargs)


def _chapter_source_text(artifact: BookArtifact, block_ids: list[str]) -> str:
    block_map = {block.block_id: block for block in artifact.blocks}
    parts = []
    for block_id in block_ids:
        block = block_map.get(block_id)
        if block and block.text:
            parts.append(block.text)
    return "\n\n".join(parts).strip()


async def _summarize_short_async(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str | None:
    """Returns None if summarization fails after all retries."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        return await _call_text_async(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
    except Exception as e:
        print(f"   \u274c Short summary failed for '{chapter_title}': {e}")
        sys.stdout.flush()
        return None


async def _summarize_detailed_async(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str | None:
    """Returns None if summarization fails after all retries."""
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        return await _call_text_async(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
    except Exception as e:
        print(f"   \u274c Detailed summary failed for '{chapter_title}': {e}")
        sys.stdout.flush()
        return None


async def summarize_chapters(
    artifact: BookArtifact,
    *,
    short_settings: LLMSettings,
    detailed_settings: LLMSettings,
    parallel_calls: int = 8,
    short_prompt_file: str = "prompt_chapter_short.md",
    detailed_prompt_file: str = "prompt_chapter_detailed.md",
) -> BookArtifact:
    artifact.stages.setdefault(CHAPTER_SUMMARIES_STAGE, StageState(name=CHAPTER_SUMMARIES_STAGE))
    stage = artifact.stages[CHAPTER_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating separate short and detailed summaries for each mapped chapter."

    chapter_count = len(artifact.chapters)
    print(f"   \u270d\ufe0f Chapter summaries: {chapter_count} chapter(s) with {parallel_calls} concurrent")
    sys.stdout.flush()

    chapter_payloads = [
        (idx, chapter.title, _chapter_source_text(artifact, chapter.blocks))
        for idx, chapter in enumerate(artifact.chapters)
    ]

    sem = asyncio.Semaphore(parallel_calls)
    total = len(chapter_payloads)

    # ---- SHORT SUMMARIES ----
    async def _do_short(idx: int, title: str, text: str) -> tuple[int, str | None]:
        print(f"   \U0001f4e4 Short sent: {title}")
        sys.stdout.flush()
        result = await _summarize_short_async(title, text, short_settings, short_prompt_file)
        if result:
            print(f"   \u2705 Short done: {title}")
        else:
            print(f"   \u274c Short FAILED: {title}")
        sys.stdout.flush()
        return idx, result

    async def _throttled_short(idx: int, title: str, text: str) -> tuple[int, str | None]:
        async with sem:
            return await _do_short(idx, title, text)

    print(f"   \U0001f525 Firing {total} short summaries ({parallel_calls} concurrent)...")
    sys.stdout.flush()
    short_results = await asyncio.gather(*[_throttled_short(idx, t, x) for idx, t, x in chapter_payloads])
    for idx, result in short_results:
        artifact.chapters[idx].short_summary = result

    short_failed = [artifact.chapters[idx].title for idx, r in short_results if r is None]

    # ---- DETAILED SUMMARIES ----
    async def _do_detail(idx: int, title: str, text: str) -> tuple[int, str | None]:
        print(f"   \U0001f4e4 Detail sent: {title}")
        sys.stdout.flush()
        result = await _summarize_detailed_async(title, text, detailed_settings, detailed_prompt_file)
        if result:
            print(f"   \u2705 Detail done: {title}")
        else:
            print(f"   \u274c Detail FAILED: {title}")
        sys.stdout.flush()
        return idx, result

    async def _throttled_detail(idx: int, title: str, text: str) -> tuple[int, str | None]:
        async with sem:
            return await _do_detail(idx, title, text)

    print(f"   \U0001f525 Firing {total} detailed summaries ({parallel_calls} concurrent)...")
    sys.stdout.flush()
    detail_results = await asyncio.gather(*[_throttled_detail(idx, t, x) for idx, t, x in chapter_payloads])
    for idx, result in detail_results:
        artifact.chapters[idx].detailed_summary = result

    detail_failed = [artifact.chapters[idx].title for idx, r in detail_results if r is None]

    # ---- REPORT ----
    all_failed = set(short_failed + detail_failed)
    if all_failed:
        stage.status = "partial"
        failures = "; ".join(sorted(all_failed))
        stage.notes = f"Summaries generated with {len(all_failed)} failure(s): {failures}"
        print(f"   \u26a0\ufe0f Chapter summaries: {chapter_count - len(short_failed)}/{chapter_count} short, "
              f"{chapter_count - len(detail_failed)}/{chapter_count} detailed OK. Failed: {failures}")
    else:
        stage.status = "done"
        stage.notes = "All chapter summaries generated successfully."
        print(f"   \u2705 Chapter summaries complete: {chapter_count} chapters")

    stage.outputs = {
        "chapter_count": chapter_count,
        "parallel_calls": parallel_calls,
        "short_model": short_settings.model,
        "detailed_model": detailed_settings.model,
        "short_failures": short_failed,
        "detail_failures": detail_failed,
    }
    sys.stdout.flush()
    return artifact.touch()


async def synthesize_overview(
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
        print("   \u26a0\ufe0f No short summaries available — skipping overview synthesis.")
        sys.stdout.flush()
        return artifact.touch()

    print(f"   \U0001f9ea Abstract: compressing {len(available)} chapter short summary(s)")
    sys.stdout.flush()

    print("   \U0001f4dd Merging chapter summaries...")
    chapter_summaries = "\n\n".join(
        f"## {chapter.title}\n{chapter.short_summary or ''}" for chapter in artifact.chapters
    ).strip()
    print(f"   \U0001f4cb Combined text: {len(chapter_summaries):,} chars")

    print(f"   \U0001f916 Calling {ultra_dense_settings.model} for abstract...")
    sys.stdout.flush()

    try:
        result = await _call_text_async(
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
            print("   \u2705 Abstract complete")
        else:
            stage.status = "failed"
            stage.notes = "Abstract call returned empty response."
            print("   \u274c Abstract returned empty — overview not written.")
    except Exception as e:
        stage.status = "failed"
        stage.notes = f"Abstract call failed: {e}"
        print(f"   \u274c Abstract failed: {e}")

    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "ultra_dense_model": ultra_dense_settings.model,
    }
    sys.stdout.flush()
    return artifact.touch()
