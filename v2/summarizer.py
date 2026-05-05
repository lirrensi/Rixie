# FILE: v2/summarizer.py
# PURPOSE: Generate chapter-level summaries and a top abstract for the V2 artifact.
# OWNS: Separate short/detailed chapter summarization and abstract synthesis stage.
# EXPORTS: summarize_chapters, synthesize_overview.
# DOCS: v2/process.py, v2/schema.py

from __future__ import annotations

import asyncio
import sys

from litellm import acompletion

from v2.cartographer import LLMSettings
from v2.pipeline import build_completion_kwargs
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
    try:
        response = await acompletion(**kwargs)
    except Exception:
        kwargs.pop("reasoning_effort", None)
        response = await acompletion(**kwargs)
    return (response.choices[0].message.content or "").strip()


def _chapter_source_text(artifact: BookArtifact, block_ids: list[str]) -> str:
    block_map = {block.block_id: block for block in artifact.blocks}
    parts = []
    for block_id in block_ids:
        block = block_map.get(block_id)
        if block and block.text:
            parts.append(block.text)
    return "\n\n".join(parts).strip()


def _fallback_short_summary(chapter_title: str, source_text: str) -> str:
    compact = " ".join(source_text.split())
    return f"{chapter_title}: {compact[:320].strip()}" + ("\u2026" if len(compact) > 320 else "")


def _fallback_detailed_summary(chapter_title: str, source_text: str) -> str:
    compact = " ".join(source_text.split())
    return f"{chapter_title}. {compact[:900].strip()}" + ("\u2026" if len(compact) > 900 else "")


async def _summarize_short_async(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str:
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        result = await _call_text_async(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
        return result or _fallback_short_summary(chapter_title, source_text)
    except Exception:
        return _fallback_short_summary(chapter_title, source_text)


async def _summarize_detailed_async(chapter_title: str, source_text: str, settings: LLMSettings, prompt_file: str) -> str:
    system = load_prompt(prompt_file)
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        result = await _call_text_async(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
        return result or _fallback_detailed_summary(chapter_title, source_text)
    except Exception:
        return _fallback_detailed_summary(chapter_title, source_text)


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

    print(f"   \u270d\ufe0f Chapter summaries: {len(artifact.chapters)} chapter(s) with {parallel_calls} concurrent")
    sys.stdout.flush()

    chapter_payloads = [
        (idx, chapter.title, _chapter_source_text(artifact, chapter.blocks))
        for idx, chapter in enumerate(artifact.chapters)
    ]

    sem = asyncio.Semaphore(parallel_calls)
    total = len(chapter_payloads)

    async def _do_short(idx: int, title: str, text: str) -> tuple[int, str]:
        print(f"   \U0001f4e4 short sent: {title}")
        sys.stdout.flush()
        result = await _summarize_short_async(title, text, short_settings, short_prompt_file)
        print(f"   \u2705 short done: {title}")
        sys.stdout.flush()
        return idx, result

    async def _throttled_short(idx: int, title: str, text: str) -> tuple[int, str]:
        async with sem:
            return await _do_short(idx, title, text)

    print(f"   \U0001f525 Firing {total} short summaries ({parallel_calls} concurrent)...")
    sys.stdout.flush()
    short_results = await asyncio.gather(*[_throttled_short(idx, t, x) for idx, t, x in chapter_payloads])
    for idx, result in short_results:
        artifact.chapters[idx].short_summary = result

    async def _do_detail(idx: int, title: str, text: str) -> tuple[int, str]:
        print(f"   \U0001f4e4 detail sent: {title}")
        sys.stdout.flush()
        result = await _summarize_detailed_async(title, text, detailed_settings, detailed_prompt_file)
        print(f"   \u2705 detail done: {title}")
        sys.stdout.flush()
        return idx, result

    async def _throttled_detail(idx: int, title: str, text: str) -> tuple[int, str]:
        async with sem:
            return await _do_detail(idx, title, text)

    print(f"   \U0001f525 Firing {total} detailed summaries ({parallel_calls} concurrent)...")
    sys.stdout.flush()
    detail_results = await asyncio.gather(*[_throttled_detail(idx, t, x) for idx, t, x in chapter_payloads])
    for idx, result in detail_results:
        artifact.chapters[idx].detailed_summary = result

    print(f"   \u2705 Chapter summaries complete: {len(artifact.chapters)} chapters")

    stage.status = "done"
    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "parallel_calls": parallel_calls,
        "short_model": short_settings.model,
        "detailed_model": detailed_settings.model,
    }
    return artifact.touch()


def _fallback_ultra_dense(text: str) -> str:
    compact = " ".join((text or "").split())
    return compact[:500].strip() + ("\u2026" if len(compact) > 500 else "")


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

    print(f"   \U0001f9ea Abstract: compressing {len(artifact.chapters)} chapter short summary(s)")
    sys.stdout.flush()

    print("   \U0001f4dd Merging chapter summaries...")
    chapter_summaries = "\n\n".join(
        f"## {chapter.title}\n{chapter.short_summary or ''}" for chapter in artifact.chapters
    ).strip()
    print(f"   \U0001f4cb Combined text: {len(chapter_summaries):,} chars")

    print(f"   \U0001f916 Calling {ultra_dense_settings.model} for abstract...")
    sys.stdout.flush()
    try:
        artifact.overview.ultra_dense_summary = await _call_text_async(
            [
                {
                    "role": "system",
                    "content": load_prompt(prompt_file),
                },
                {"role": "user", "content": chapter_summaries},
            ],
            ultra_dense_settings,
        ) or _fallback_ultra_dense(chapter_summaries)
    except Exception:
        artifact.overview.ultra_dense_summary = _fallback_ultra_dense(chapter_summaries)

    stage.status = "done"
    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "ultra_dense_model": ultra_dense_settings.model,
    }
    print("   \u2705 Abstract complete")
    return artifact.touch()
