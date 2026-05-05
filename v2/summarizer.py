# FILE: v2/summarizer.py
# PURPOSE: Generate chapter-level summaries and a top abstract for the V2 artifact.
# OWNS: Separate short/detailed chapter summarization and abstract synthesis stage.
# EXPORTS: summarize_chapters, synthesize_overview.
# DOCS: v2/process.py, v2/schema.py

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from v2.cartographer import LLMSettings
from v2.pipeline import build_completion_kwargs, completion
from v2.prompts import load_prompt
from v2.schema import BookArtifact, StageState

CHAPTER_SUMMARIES_STAGE = "chapter_summaries"
OVERVIEW_STAGE = "overview"


def _call_text(messages: list[dict], settings: LLMSettings) -> str:
    kwargs = build_completion_kwargs(settings.model, messages, temperature=settings.temperature)
    if settings.api_base:
        kwargs["api_base"] = settings.api_base
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.timeout:
        kwargs["timeout"] = settings.timeout
    response = completion(**kwargs)
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
    return f"{chapter_title}: {compact[:320].strip()}" + ("…" if len(compact) > 320 else "")


def _fallback_detailed_summary(chapter_title: str, source_text: str) -> str:
    compact = " ".join(source_text.split())
    return f"{chapter_title}. {compact[:900].strip()}" + ("…" if len(compact) > 900 else "")


def _summarize_short(chapter_title: str, source_text: str, settings: LLMSettings) -> str:
    system = load_prompt("prompt_chapter_short.md")
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        result = _call_text(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
        return result or _fallback_short_summary(chapter_title, source_text)
    except Exception:
        return _fallback_short_summary(chapter_title, source_text)


def _summarize_detailed(chapter_title: str, source_text: str, settings: LLMSettings) -> str:
    system = load_prompt("prompt_chapter_detailed.md")
    user = f"CHAPTER TITLE: {chapter_title}\n\nSOURCE TEXT:\n{source_text}"
    try:
        result = _call_text(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            settings,
        )
        return result or _fallback_detailed_summary(chapter_title, source_text)
    except Exception:
        return _fallback_detailed_summary(chapter_title, source_text)


def summarize_chapters(
    artifact: BookArtifact,
    *,
    short_settings: LLMSettings,
    detailed_settings: LLMSettings,
    parallel_calls: int = 8,
) -> BookArtifact:
    artifact.stages.setdefault(CHAPTER_SUMMARIES_STAGE, StageState(name=CHAPTER_SUMMARIES_STAGE))
    stage = artifact.stages[CHAPTER_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating separate short and detailed summaries for each mapped chapter."

    print(f"   ✍️ Chapter summaries: {len(artifact.chapters)} chapter(s)")

    chapter_payloads = [
        (idx, chapter.title, _chapter_source_text(artifact, chapter.blocks))
        for idx, chapter in enumerate(artifact.chapters)
    ]
    max_workers = max(1, parallel_calls)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        short_jobs = {
            executor.submit(_summarize_short, title, text, short_settings): idx
            for idx, title, text in chapter_payloads
        }
        completed = 0
        for future in as_completed(short_jobs):
            idx = short_jobs[future]
            artifact.chapters[idx].short_summary = future.result()
            completed += 1
            print(f"   • short {completed}/{len(chapter_payloads)}: {artifact.chapters[idx].title}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        detailed_jobs = {
            executor.submit(_summarize_detailed, title, text, detailed_settings): idx
            for idx, title, text in chapter_payloads
        }
        completed = 0
        for future in as_completed(detailed_jobs):
            idx = detailed_jobs[future]
            artifact.chapters[idx].detailed_summary = future.result()
            completed += 1
            print(f"   • detail {completed}/{len(chapter_payloads)}: {artifact.chapters[idx].title}")

    stage.status = "done"
    stage.outputs = {
        "chapter_count": len(artifact.chapters),
        "parallel_calls": max_workers,
        "short_model": short_settings.model,
        "detailed_model": detailed_settings.model,
    }
    return artifact.touch()


def _fallback_ultra_dense(text: str) -> str:
    compact = " ".join((text or "").split())
    return compact[:500].strip() + ("…" if len(compact) > 500 else "")


def synthesize_overview(
    artifact: BookArtifact,
    *,
    ultra_dense_settings: LLMSettings,
) -> BookArtifact:
    artifact.stages.setdefault(OVERVIEW_STAGE, StageState(name=OVERVIEW_STAGE))
    stage = artifact.stages[OVERVIEW_STAGE]
    stage.status = "running"
    stage.notes = "Building a top abstract from chapter short summaries."

    print(f"   🧪 Abstract: compressing {len(artifact.chapters)} chapter short summary(s)")

    chapter_summaries = "\n\n".join(
        f"## {chapter.title}\n{chapter.short_summary or ''}" for chapter in artifact.chapters
    ).strip()

    try:
        artifact.overview.ultra_dense_summary = _call_text(
            [
                {
                    "role": "system",
                    "content": load_prompt("prompt_ultra_dense.md"),
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
    print("   ✅ Abstract complete")
    return artifact.touch()
