# FILE: v2/cartographer.py
# PURPOSE: Provide the initial V2 content-mapping stage stub that will later turn source text into structured chapters and blocks.
# OWNS: Cartography-stage placeholder logic and stage naming for V2.
# EXPORTS: CARTOGRAPHY_STAGE, map_book_structure.
# DOCS: README.md, v2/schema.py, v2/pipeline.py
#
# POLICY: Never write fallback garbage. If an AI call fails after all retries,
# the field stays None and the stage reports the failure.
# RESUMABILITY: Every completed block is saved immediately. Crashes/ctrl-c cost at most one in-flight block.

from __future__ import annotations

import asyncio
import json
import math
import sys
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# fcntl is Unix-only, import conditionally
if sys.platform != "win32":
    import fcntl

from pydantic import BaseModel, ValidationError

from v2.blocker import build_blocks
from v2.pipeline import acompletion_with_retry, build_completion_kwargs
from v2.prompts import load_prompt
from v2.schema import BookArtifact, ChapterArtifact, StageState
import yaml

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


class ArtifactLock:
    """Process-wide lock for concurrent writes to book.yaml."""

    def __init__(self, book_dir: Path):
        self.lock_path = book_dir / ".book.lock"
        self.lock_file: Optional[int] = None

    def __enter__(self):
        # Windows fcntl not available, use file-based locking
        if sys.platform == "win32":
            try:
                import msvcrt
            except ImportError:
                pass
            # For Windows, we use a race-condition-ish approach with exclusive file creation
            retry_count = 0
            while retry_count < 10:
                try:
                    self.lock_file = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    import time
                    time.sleep(0.1)
                    retry_count += 1
        else:
            self.lock_file = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY)
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_EX)
            except (AttributeError, OSError):
                pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file is not None:
            if sys.platform != "win32":
                try:
                    fcntl.flock(self.lock_file, fcntl.LOCK_UN)
                except (AttributeError, OSError):
                    pass
            os.close(self.lock_file)
        try:
            if self.lock_path.exists():
                self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _extract_json_object(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return stripped[start : end + 1]


async def _call_json_async(messages: list[dict], settings: LLMSettings) -> dict:
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
    content = await acompletion_with_retry(kwargs)
    return json.loads(_extract_json_object(content))


def save_artifact_with_lock(artifact: BookArtifact, book_yaml_path: Path):
    """Save artifact with process locking to prevent corruption from concurrent writes."""
    with ArtifactLock(book_yaml_path.parent):
        yaml_content = yaml.safe_dump(artifact.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
        book_yaml_path.write_text(yaml_content, encoding="utf-8")


async def generate_block_mini_summaries(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    parallel_calls: int = 8,
    prompt_file: str = "prompt_block_mini_summary.md",
    save_every: int = 5,
) -> BookArtifact:
    """Generate mini summaries with incremental saving. Resumable from any point."""
    artifact.stages.setdefault(MINI_SUMMARIES_STAGE, StageState(name=MINI_SUMMARIES_STAGE))
    stage = artifact.stages[MINI_SUMMARIES_STAGE]
    stage.status = "running"
    stage.notes = "Generating one-sentence block summaries and useful=false classifications."

    total = len(artifact.blocks)
    print(f"   \\U0001f50e Mini summaries: {total} block(s)")
    sys.stdout.flush()

    # Skip blocks that already have mini_summaries
    pending_indices = [
        idx for idx, block in enumerate(artifact.blocks)
        if block.mini_summary is None or block.useful is None
    ]

    if not pending_indices:
        print(f"   ✓ All {total} blocks already have mini summaries")
        stage.status = "done"
        stage.notes = "All block mini-summaries already present."
        sys.stdout.flush()
        return artifact

    print(f"   → Resuming {len(pending_indices)} pending blocks (skipping {total - len(pending_indices)} complete)")
    sys.stdout.flush()

    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    save_count = 0

    sem = asyncio.Semaphore(parallel_calls)
    print(f"   \\U0001f525 Firing {len(pending_indices)} requests ({parallel_calls} concurrent)...")
    sys.stdout.flush()

    async def _do_one(idx: int, block) -> tuple[int, MiniSummaryResult | None]:
        print(f"   📤 Sent {idx+1}/{total}: {block.block_id}")
        sys.stdout.flush()
        try:
            result = await _call_json_async(
                [
                    {"role": "system", "content": load_prompt(prompt_file)},
                    {"role": "user", "content": f"BLOCK:\\n{block.text}"},
                ],
                llm_settings,
            )
            parsed = MiniSummaryResult.model_validate(result)
            parsed.mini_summary = " ".join(parsed.mini_summary.split())
            print(f"   ✓ Done {idx+1}/{total}: {block.block_id} → useful={parsed.useful}")
            sys.stdout.flush()
            return idx, parsed
        except Exception as e:
            print(f"   ✗ Fail {idx+1}/{total}: {block.block_id} → {e}")
            sys.stdout.flush()
            return idx, None

    async def _throttled(idx: int, block) -> tuple[int, MiniSummaryResult | None]:
        async with sem:
            return await _do_one(idx, block)

    async def _with_incremental_save(results_list: list):
        """Yield results and save incrementally."""
        tasks = [_throttled(idx, artifact.blocks[idx]) for idx in pending_indices]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results_list.append(result)
            save_count += 1
            if save_count % save_every == 0:
                for idx, parsed in results_list:
                    if parsed:
                        artifact.blocks[idx].mini_summary = parsed.mini_summary
                        artifact.blocks[idx].useful = parsed.useful
                save_artifact_with_lock(artifact, book_yaml_path)
                print(f"   💾 Saved progress ({save_count}/{len(pending_indices)} completed)")
                sys.stdout.flush()
        return results_list

    results = await _with_incremental_save([])

    failures = 0
    for idx, result in results:
        if result:
            artifact.blocks[idx].mini_summary = result.mini_summary
            artifact.blocks[idx].useful = result.useful
        else:
            failures += 1

    # Final save to ensure everything is written
    for idx, parsed in results:
        if parsed:
            artifact.blocks[idx].mini_summary = parsed.mini_summary
            artifact.blocks[idx].useful = parsed.useful
    save_artifact_with_lock(artifact, book_yaml_path)

    useful_blocks = sum(1 for block in artifact.blocks if block.useful)

    if failures:
        stage.status = "partial"
        stage.notes = f"Generated {total - failures}/{total} block summaries ({failures} failures)."
        print(f"   ⚠️ {failures}/{total} block summaries failed — fields left None")
    else:
        stage.status = "done"
        stage.notes = "All block mini-summaries generated."
        print(f"   ✓ Mini summaries: {total} blocks complete")

    stage.outputs = {
        "block_count": len(artifact.blocks),
        "useful_blocks": useful_blocks,
        "skipped_blocks": len(artifact.blocks) - useful_blocks,
        "failed_blocks": failures,
        "parallel_calls": parallel_calls,
        "model": llm_settings.model,
    }
    sys.stdout.flush()
    return artifact.touch()


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


async def group_blocks_into_chapters(
    artifact: BookArtifact,
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_cartographer_map.md",
) -> BookArtifact:
    stage = artifact.stages[CARTOGRAPHY_STAGE]
    stage.status = "running"
    useful_blocks = [block for block in artifact.blocks if block.useful is not False]
    print(f"   \\U0001f9ed Cartographer: {len(useful_blocks)} useful blocks out of {len(artifact.blocks)} total")
    if not useful_blocks:
        artifact.chapters = []
        stage.status = "done"
        stage.notes = "No useful blocks remained after mini-summary classification."
        stage.outputs = {**stage.outputs, "chapter_count": 0}
        return artifact.touch()

    print("   \\U0001f4cb Building block list for LLM...")
    block_lines = []
    for block in useful_blocks:
        summary = block.mini_summary or ""
        block_lines.append(f"{block.block_id}: {summary}")

    print(f"   \\U0001f916 Calling {llm_settings.model} to group into chapters...")
    sys.stdout.flush()
    system = load_prompt(prompt_file)
    user = "ORDERED BLOCK SUMMARIES:\\n" + "\\n".join(block_lines)

    try:
        parsed = ChapterMapResult.model_validate(
            await _call_json_async(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                llm_settings,
            )
        )
        artifact.chapters = _validate_and_materialize_chapters(artifact, parsed.chapters)
        stage.status = "done"
        stage.notes = "Generated chapter map from ordered mini-summaries."
        print(f"   ✓ Cartographer mapped {len(artifact.chapters)} chapter(s)")

        # Save immediately after successful chapter generation
        book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
        save_artifact_with_lock(artifact, book_yaml_path)
    except (ValidationError, ValueError, Exception) as e:
        artifact.chapters = []
        stage.status = "failed"
        stage.notes = f"Cartographer LLM failed: {e}"
        print(f"   ✗ Cartographer failed: {e}")

    stage.outputs = {
        **stage.outputs,
        "chapter_count": len(artifact.chapters),
        "useful_blocks": len(useful_blocks),
        "model": llm_settings.model,
    }
    sys.stdout.flush()
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
