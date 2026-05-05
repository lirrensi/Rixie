# FILE: v2/cartographer.py
# PURPOSE: Provide the initial V2 content-mapping stage stub that will later turn source text into structured chapters and blocks.
# OWNS: Cartography-stage placeholder logic and stage naming for V2.
# EXPORTS: CARTOGRAPHY_STAGE, map_book_structure.
# DOCS: README.md, v2/schema.py, v2/pipeline.py

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from v2.blocker import build_blocks
from v2.pipeline import build_completion_kwargs, completion
from v2.prompts import load_prompt
from v2.schema import BookArtifact, ChapterArtifact, StageState

CARTOGRAPHY_STAGE = "cartography"
MINI_SUMMARIES_STAGE = "mini_summaries"


class MiniSummaryResult(BaseModel):
    mini_summary: str
    useful: bool


class ChapterRange(BaseModel):
    title: str
    block_start: str
    block_end: str


class ChapterMapResult(BaseModel):
    chapters: list[ChapterRange]


@dataclass
class LLMSettings:
    model: str
    temperature: float
    api_base: str | None = None
    api_key: str | None = None
    timeout: int | None = None
    thinking: bool = True


def _extract_json_object(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return stripped[start : end + 1]


def _call_json(messages: list[dict], settings: LLMSettings) -> dict:
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
        response = completion(**kwargs)
    except Exception:
        kwargs.pop("reasoning_effort", None)
        response = completion(**kwargs)
    content = response.choices[0].message.content or ""
    return json.loads(_extract_json_object(content))


def _fallback_block_summary(text: str) -> MiniSummaryResult:
    clean = " ".join((text or "").split())
    short = clean[:220].strip()
    if len(clean) > 220:
        short += "…"
    useful = not any(
        marker in clean.lower()
        for marker in ["table of contents", "copyright", "references", "bibliography", "index"]
    )
    return MiniSummaryResult(
        mini_summary=short or "Low-information block with no reliable summary.",
        useful=useful,
    )


def _summarize_block(block_text: str, settings: LLMSettings, prompt_file: str) -> MiniSummaryResult:
    system = load_prompt(prompt_file)
    user = f"BLOCK:\n{block_text}"
    try:
        parsed = MiniSummaryResult.model_validate(
            _call_json(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                settings,
            )
        )
        parsed.mini_summary = " ".join(parsed.mini_summary.split())
        return parsed
    except Exception:
        return _fallback_block_summary(block_text)


def generate_block_mini_summaries(
    artifact: BookArtifact,
    *,
    llm_settings: LLMSettings,
    parallel_calls: int = 8,
    prompt_file: str = "prompt_block_mini_summary.md",
) -> BookArtifact:
    artifact.stages.setdefault(MINI_SUMMARIES_STAGE, StageState(name=MINI_SUMMARIES_STAGE))
    stage = artifact.stages[MINI_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating one-sentence block summaries and useful=false classifications."

    total = len(artifact.blocks)
    print(f"   🔎 Mini summaries: {total} block(s)")
    sys.stdout.flush()

    max_workers = max(1, parallel_calls)
    print(f"   🔥 Firing {total} requests in parallel ({max_workers} at a time)...")
    sys.stdout.flush()

    results: dict[int, MiniSummaryResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending = {}
        for idx, block in enumerate(artifact.blocks):
            f = executor.submit(_summarize_block, block.text or "", llm_settings, prompt_file)
            pending[f] = idx
            print(f"   📤 Sent {idx+1}/{total}: {block.block_id}")
            sys.stdout.flush()

        for future in as_completed(pending):
            idx = pending[future]
            try:
                result = future.result()
                results[idx] = result
                print(f"   ✅ Done {len(results)}/{total}: {artifact.blocks[idx].block_id} → useful={result.useful}")
                sys.stdout.flush()
            except Exception as e:
                results[idx] = _fallback_block_summary(artifact.blocks[idx].text or "")
                print(f"   ❌ Fail {idx+1}/{total}: {artifact.blocks[idx].block_id} → {e}")
                sys.stdout.flush()

    for idx, result in sorted(results.items()):
        artifact.blocks[idx].mini_summary = result.mini_summary
        artifact.blocks[idx].useful = result.useful

    useful_blocks = sum(1 for block in artifact.blocks if block.useful)
    stage.status = "done"
    stage.outputs = {
        "block_count": len(artifact.blocks),
        "useful_blocks": useful_blocks,
        "skipped_blocks": len(artifact.blocks) - useful_blocks,
        "parallel_calls": max_workers,
        "model": llm_settings.model,
    }
    return artifact.touch()


def _group_fallback(artifact: BookArtifact) -> list[ChapterRange]:
    useful_blocks = [block for block in artifact.blocks if block.useful is not False]
    if not useful_blocks:
        return []
    group_size = max(3, math.ceil(len(useful_blocks) / 8))
    chapters: list[ChapterRange] = []
    for i in range(0, len(useful_blocks), group_size):
        chunk = useful_blocks[i : i + group_size]
        chapters.append(
            ChapterRange(
                title=f"Section {len(chapters) + 1}",
                block_start=chunk[0].block_id,
                block_end=chunk[-1].block_id,
            )
        )
    return chapters


def _validate_and_materialize_chapters(artifact: BookArtifact, chapter_ranges: list[ChapterRange]) -> list[ChapterArtifact]:
    by_id = {block.block_id: block for block in artifact.blocks}
    useful_ids = [block.block_id for block in artifact.blocks if block.useful is not False]
    if not useful_ids:
        return []

    chapters: list[ChapterArtifact] = []
    covered: list[str] = []
    for order, chapter in enumerate(chapter_ranges, start=1):
        if chapter.block_start not in by_id or chapter.block_end not in by_id:
            raise ValueError("Chapter references unknown block ids")
        start_idx = useful_ids.index(chapter.block_start)
        end_idx = useful_ids.index(chapter.block_end)
        if end_idx < start_idx:
            raise ValueError("Chapter end occurs before chapter start")
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

    if covered != useful_ids:
        raise ValueError("Chapter coverage is incomplete or non-contiguous")
    return chapters


def group_blocks_into_chapters(
    artifact: BookArtifact,
    *,
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_cartographer_map.md",
) -> BookArtifact:
    stage = artifact.stages[CARTOGRAPHY_STAGE]
    stage.status = "running"
    useful_blocks = [block for block in artifact.blocks if block.useful is not False]
    print(f"   🧭 Cartographer: {len(useful_blocks)} useful blocks out of {len(artifact.blocks)} total")
    if not useful_blocks:
        artifact.chapters = []
        stage.status = "done"
        stage.notes = "No useful blocks remained after mini-summary classification."
        stage.outputs = {**stage.outputs, "chapter_count": 0}
        return artifact.touch()

    print(f"   📋 Building block list for LLM...")
    block_lines = []
    for block in useful_blocks:
        summary = block.mini_summary or ""
        block_lines.append(f"{block.block_id}: {summary}")

    print(f"   🤖 Calling {llm_settings.model} to group into chapters...")
    system = load_prompt(prompt_file)
    user = "ORDERED BLOCK SUMMARIES:\n" + "\n".join(block_lines)

    system = load_prompt(prompt_file)
    user = "ORDERED BLOCK SUMMARIES:\n" + "\n".join(block_lines)

    try:
        parsed = ChapterMapResult.model_validate(
            _call_json(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                llm_settings,
            )
        )
        artifact.chapters = _validate_and_materialize_chapters(artifact, parsed.chapters)
        stage.notes = "Generated chapter map from ordered mini-summaries."
    except (ValidationError, ValueError, Exception):
        fallback = _group_fallback(artifact)
        artifact.chapters = _validate_and_materialize_chapters(artifact, fallback)
        stage.notes = "Cartographer LLM output failed validation; used deterministic fallback grouping."

    stage.status = "done"
    print(f"   ✅ Cartographer mapped {len(artifact.chapters)} chapter(s)")
    stage.outputs = {
        **stage.outputs,
        "chapter_count": len(artifact.chapters),
        "useful_blocks": len(useful_blocks),
        "model": llm_settings.model,
    }
    return artifact.touch()


def map_book_structure(
    artifact: BookArtifact,
    source_text: str,
    target_tokens: int = 1024,
    min_tokens: int = 768,
    max_tokens: int = 1280,
    encoding_model: str = "gpt-4o-mini",
) -> BookArtifact:
    print(f"   📊 Tokenizing with {encoding_model}...")
    artifact.stages.setdefault(CARTOGRAPHY_STAGE, StageState(name=CARTOGRAPHY_STAGE))
    artifact.blocks = build_blocks(
        source_text,
        target_tokens=target_tokens,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        encoding_model=encoding_model,
    )
    print(f"   ✂️  Split into {len(artifact.blocks)} blocks")
    artifact.stages[CARTOGRAPHY_STAGE].notes = (
        "Block anchors generated. TODO: create mini-summaries and group them into chapters."
    )
    artifact.stages[CARTOGRAPHY_STAGE].status = "ready"
    artifact.stages[CARTOGRAPHY_STAGE].outputs = {
        "block_count": len(artifact.blocks),
        "target_tokens": target_tokens,
        "min_tokens": min_tokens,
        "max_tokens": max_tokens,
        "encoding_model": encoding_model,
    }
    return artifact.touch()
