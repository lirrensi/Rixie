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

import json
import sys
import os
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from v2.blocker import build_blocks
from v2.pipeline import completion_with_retry, build_completion_kwargs
from v2.prompts import load_prompt
from v2.schema import BookArtifact, ChapterArtifact, StageState
import yaml

CARTOGRAPHY_STAGE = "cartography"
MINI_SUMMARIES_STAGE = "mini_summaries"


class MiniSummaryResult(BaseModel):
    mini_summary: str | None  # Allow null when useful=false
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





def _pydantic_to_json_schema(pydantic_model: type[BaseModel]) -> dict:
    """Convert a Pydantic model to JSON Schema format for structured output."""
    schema = pydantic_model.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": schema,
    }


def _call_json_sync(
    messages: list[dict],
    settings: LLMSettings,
    response_model: type[BaseModel],
) -> BaseModel:
    """Call LLM with structured output guarantee - SYNCHRONOUS."""
    import traceback

    print(f"      🔧 _call_json_sync ENTER", flush=True)
    print(f"      📖 Response model: {response_model.__name__}", flush=True)

    schema = _pydantic_to_json_schema(response_model)
    print(f"      📋 JSON Schema: {schema['type']}", flush=True)
    print(f"      📋 Schema keys: {list(schema['json_schema'].keys())}", flush=True)

    kwargs = build_completion_kwargs(
        settings.model,
        messages,
        temperature=settings.temperature,
        thinking=settings.thinking,
        response_format=schema,
    )
    if settings.api_base:
        kwargs["api_base"] = settings.api_base
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.timeout:
        kwargs["timeout"] = settings.timeout

    print(f"      🔗 Kwargs keys: {list(kwargs.keys())}", flush=True)
    print(f"      📨 About to call completion_with_retry...", flush=True)

    try:
        content = completion_with_retry(kwargs)
        print(f"      ✅ Got response from LLM, length: {len(content)} chars", flush=True)
        print(f"      📝 Response preview: {content[:500]}", flush=True)

        parsed = response_model.model_validate_json(content)
        print(f"      ✅ Pydantic validation successful", flush=True)
        print(f"      📦 Parsed result: {parsed}", flush=True)

        return parsed
    except Exception as e:
        print(f"      ❌ ERROR in _call_json_sync: {type(e).__name__}: {e}", flush=True)
        print(f"      ❌ TRACEBACK:", flush=True)
        print(traceback.format_exc(), flush=True)
        raise


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
) -> BookArtifact:
    """Generate mini summaries SEQUENTIALLY with BLOCKING SYNC saves after each block."""
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

    print(f"   🔥 Processing {len(pending_indices)} blocks SEQUENTIALLY - NO PARALLEL", flush=True)
    save_count = 0

    # Process ONE block at a time
    for idx in pending_indices:
        block = artifact.blocks[idx]
        print(f"   📤 Processing {idx+1}/{total}: {block.block_id}", flush=True)

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

            # TRUE SYNC SAVE to disk - BLOCKING until complete
            save_artifact_with_lock(artifact, book_yaml_path)

            # VERIFY save by re-reading
            verify_data = book_yaml_path.read_text(encoding="utf-8")
            verify_yaml = yaml.safe_load(verify_data)
            verify_block = verify_yaml['blocks'][idx]

            if verify_block['mini_summary'] != result.mini_summary or verify_block['useful'] != result.useful:
                print(f"   ❌ VERIFY FAILED for block {idx+1} - SAVE CORRUPT!", flush=True)
                raise RuntimeError(f"Save verification failed for block {idx+1}")

            print(f"   ✓ Done {idx+1}/{total}: {block.block_id} → useful={result.useful}", flush=True)

        except Exception as e:
            print(f"   ✗ Fail {idx+1}/{total}: {block.block_id} → {e}", flush=True)
            # Still save even failed blocks for resume capability

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
    workspace_dir: Path,
    *,
    llm_settings: LLMSettings,
    prompt_file: str = "prompt_cartographer_map.md",
) -> BookArtifact:
    """Group blocks into chapters - SYNCHRONOUS."""
    import traceback

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
    block_lines = []
    for block in useful_blocks:
        summary = block.mini_summary or ""
        line = f"{block.block_id}: {summary}"
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

    print(f"\n🤖 Calling {llm_settings.model} to group into chapters...", flush=True)
    print(f"🔧 LLM settings:")
    print(f"    model: {llm_settings.model}")
    print(f"    temperature: {llm_settings.temperature}")
    print(f"    thinking: {llm_settings.thinking}")
    print(f"    api_base: {llm_settings.api_base}")
    print(f"    api_key: {llm_settings.api_key}")
    print(f"    timeout: {llm_settings.timeout}")
    sys.stdout.flush()

    try:
        print(f"\n🚀 About to call _call_json_sync...")
        parsed = _call_json_sync(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            llm_settings,
            response_model=ChapterMapResult,
        )
        print(f"\n✅ Got response!")
        print(f"📚 Parsed {len(parsed.chapters)} chapter(s) from response")
        for i, chapter in enumerate(parsed.chapters):
            print(f"  Chapter {i+1}: {chapter.title}")
            print(f"    Start: {chapter.block_start}, End: {chapter.block_end}")

        artifact.chapters = _validate_and_materialize_chapters(artifact, parsed.chapters)
        stage.status = "done"
        stage.notes = "Generated chapter map from ordered mini-summaries."
        print(f"\n✓ Cartographer mapped {len(artifact.chapters)} chapter(s)")

        # SYNC SAVE & VERIFY chapter mapping
        book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
        save_artifact_with_lock(artifact, book_yaml_path)

        # VERIFY chapter data saved correctly
        verify_data = yaml.safe_load(book_yaml_path.read_text(encoding="utf-8"))
        if len(verify_data.get('chapters', [])) != len(artifact.chapters):
            print(f"   ❌ VERIFY FAILED - chapters count mismatch!", flush=True)
            raise RuntimeError("Chapter save verification failed")

        print(f"💾 SAVED & VERIFIED chapter mapping", flush=True)
    except (ValidationError, ValueError, Exception) as e:
        print(f"\n❌ ERROR TYPE: {type(e).__name__}")
        print(f"❌ ERROR MSG: {e}")
        print(f"\n❌ FULL TRACEBACK:")
        print(traceback.format_exc(), flush=True)
        artifact.chapters = []
        stage.status = "failed"
        stage.notes = f"Cartographer LLM failed: {e}"
        print(f"\n✗ Cartographer failed: {e}")

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
    print(f"   📊 Tokenizing with {encoding_model}...", flush=True)
    artifact.stages.setdefault(CARTOGRAPHY_STAGE, StageState(name=CARTOGRAPHY_STAGE))
    artifact.blocks = build_blocks(
        source_text,
        target_tokens=target_tokens,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        encoding_model=encoding_model,
    )
    print(f"   ✂️  Split into {len(artifact.blocks)} blocks", flush=True)
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
