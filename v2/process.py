# FILE: v2/process.py
# PURPOSE: Bootstrap a V2 per-book workspace with source.md and book.yaml while later stages remain intentionally stubbed.
# OWNS: V2 CLI scaffolding, workspace preparation, and initial artifact persistence.
# EXPORTS: main, prepare_workspace.
# DOCS: README.md, v2/schema.py, v2/pipeline.py

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v2.cartographer import LLMSettings, generate_block_mini_summaries, group_blocks_into_chapters, map_book_structure
from v2.config import load_repo_config, load_v2_config, resolve_profile
from v2.ingest import detect_format, ingest_source
from v2.renderer import render_outputs
from v2.schema import BookArtifact, DocumentMetadata, StageState
from v2.summarizer import summarize_chapters, synthesize_overview

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"
DEFAULT_V2_BOOKS_DIR = REPO_ROOT / "output" / "v2"


def slugify(name: str) -> str:
    stem = Path(name).stem if name else "book"
    slug = re.sub(r"[^\w\s-]", "", stem).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug or "book"


def find_books(input_dir: Path) -> list[Path]:
    books: list[Path] = []
    for ext in ["*.md", "*.epub", "*.txt", "*.pdf"]:
        books.extend(input_dir.glob(ext))
    return sorted(books, key=lambda p: p.name.lower())


def build_artifact(source_path: Path | None, slug: str) -> BookArtifact:
    title = source_path.stem if source_path else slug.replace("-", " ").title()
    artifact = BookArtifact(
        metadata=DocumentMetadata(
            title=title,
            slug=slug,
            source_path=str(source_path) if source_path else "",
            source_format=detect_format(source_path),
        ),
        stages={
            "ingest": StageState(name="ingest", status="done", notes="Workspace scaffold created."),
            "mini_summaries": StageState(name="mini_summaries", status="pending"),
            "cartography": StageState(name="cartography", status="pending"),
            "chapter_summaries": StageState(name="chapter_summaries", status="pending"),
            "overview": StageState(name="overview", status="pending"),
            "render": StageState(name="render", status="pending"),
        },
        notes=["V2 scaffold initialized."],
    )
    return artifact.touch()


def ensure_stage_defaults(artifact: BookArtifact) -> BookArtifact:
    stage_names = ["ingest", "mini_summaries", "cartography", "chapter_summaries", "overview", "render"]
    for stage_name in stage_names:
        artifact.stages.setdefault(stage_name, StageState(name=stage_name))
    return artifact


def load_artifact(book_yaml_path: Path) -> BookArtifact:
    data = yaml.safe_load(book_yaml_path.read_text(encoding="utf-8")) or {}
    return ensure_stage_defaults(BookArtifact.model_validate(data))


def load_or_ingest_source(source_path: Path | None, source_md_path: Path, workspace_dir: Path) -> str:
    if source_md_path.exists():
        return source_md_path.read_text(encoding="utf-8")
    source_text = ingest_source(source_path, workspace_dir)
    source_md_path.write_text(source_text, encoding="utf-8")
    return source_text


def save_artifact(artifact: BookArtifact, source_text: str, workspace_dir: Path) -> tuple[Path, Path]:
    source_md_path = workspace_dir / artifact.metadata.source_md
    book_yaml_path = workspace_dir / artifact.metadata.artifact_yaml
    source_md_path.write_text(source_text, encoding="utf-8")
    book_yaml_path.write_text(
        yaml.safe_dump(artifact.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return source_md_path, book_yaml_path


def prepare_workspace(
    source_path: Path | None,
    books_dir: Path = DEFAULT_V2_BOOKS_DIR,
    target_tokens: int = 1024,
    min_tokens: int = 768,
    max_tokens: int = 1280,
    encoding_model: str = "gpt-4o-mini",
    mini_summary_settings: LLMSettings | None = None,
    cartographer_settings: LLMSettings | None = None,
    short_summary_settings: LLMSettings | None = None,
    detailed_summary_settings: LLMSettings | None = None,
    ultra_dense_settings: LLMSettings | None = None,
    mini_summary_profile: dict | None = None,
    cartography_profile: dict | None = None,
    chapter_short_profile: dict | None = None,
    chapter_long_profile: dict | None = None,
    parallel_calls: int = 8,
    max_blocks: int | None = None,
) -> tuple[Path, Path, Path]:
    slug = slugify(source_path.name if source_path else "book")
    workspace_dir = books_dir / slug
    workspace_dir.mkdir(parents=True, exist_ok=True)

    source_md_path = workspace_dir / "source.md"
    book_yaml_path = workspace_dir / "book.yaml"
    resume = book_yaml_path.exists()

    if resume:
        artifact = load_artifact(book_yaml_path)
        print(f"↻ Resuming V2 workspace: {workspace_dir}")
    else:
        artifact = build_artifact(source_path, slug)
        print(f"🆕 Creating V2 workspace: {workspace_dir}")

    source_text = load_or_ingest_source(source_path, source_md_path, workspace_dir)
    artifact = ensure_stage_defaults(artifact)

    ingest_stage = artifact.stages["ingest"]
    if ingest_stage.status != "done" or not ingest_stage.outputs:
        print("   [1/6] Ingesting source...")
        ingest_stage.status = "done"
        ingest_stage.notes = ingest_stage.notes or "Source normalized into source.md."
        ingest_stage.outputs = {
            "source_chars": len(source_text),
            "source_format": artifact.metadata.source_format,
        }
        source_md_path.write_text(source_text, encoding="utf-8")
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    else:
        print("   [1/6] Ingest skipped (already complete)")

    cartography_stage = artifact.stages["cartography"]
    if cartography_stage.status != "done" or not artifact.blocks:
        print("   [2/6] Building block map...")
        artifact = map_book_structure(
            artifact,
            source_text,
            target_tokens=target_tokens,
            min_tokens=min_tokens,
            max_tokens=max_tokens,
            encoding_model=encoding_model,
        )
        if max_blocks is not None and max_blocks > 0:
            artifact.blocks = artifact.blocks[:max_blocks]
            artifact.stages["cartography"].outputs["block_count"] = len(artifact.blocks)
            artifact.notes.append(f"Smoke-test limit applied: first {len(artifact.blocks)} blocks only.")
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    else:
        print(f"   [2/6] Block map skipped ({len(artifact.blocks)} blocks already mapped)")

    if mini_summary_settings and artifact.blocks and artifact.stages["mini_summaries"].status != "done":
        print("   [3/6] Generating block mini summaries...")
        artifact = generate_block_mini_summaries(
            artifact,
            llm_settings=mini_summary_settings,
            parallel_calls=parallel_calls,
            prompt_file=str(mini_summary_profile.get("prompt_file", "prompt_block_mini_summary.md")),
        )
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    elif artifact.stages["mini_summaries"].status == "done":
        print("   [3/6] Mini summaries skipped (already complete)")

    if cartographer_settings and artifact.blocks and not artifact.chapters:
        print("   [4/6] Grouping blocks into chapters...")
        artifact = group_blocks_into_chapters(
            artifact,
            llm_settings=cartographer_settings,
            prompt_file=str(cartography_profile.get("prompt_file", "prompt_cartographer_map.md")),
        )
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    elif artifact.chapters:
        print(f"   [4/6] Chapter grouping skipped ({len(artifact.chapters)} chapters already mapped)")
    elif not artifact.chapters:
        print("   [4/6] Chapter grouping unavailable (no chapters yet)")

    if short_summary_settings and detailed_summary_settings and artifact.chapters and artifact.stages["chapter_summaries"].status != "done":
        print("   [5/6] Writing chapter summaries...")
        artifact = summarize_chapters(
            artifact,
            short_settings=short_summary_settings,
            detailed_settings=detailed_summary_settings,
            parallel_calls=parallel_calls,
            short_prompt_file=str(chapter_short_profile.get("prompt_file", "prompt_chapter_short.md")),
            detailed_prompt_file=str(chapter_long_profile.get("prompt_file", "prompt_chapter_detailed.md")),
        )
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    elif artifact.stages["chapter_summaries"].status == "done":
        print("   [5/6] Chapter summaries skipped (already complete)")

    if ultra_dense_settings and artifact.chapters and artifact.stages["overview"].status != "done":
        print("   [6/6] Building abstract...")
        artifact = synthesize_overview(
            artifact,
            ultra_dense_settings=ultra_dense_settings,
            prompt_file=str(overview_profile.get("prompt_file", "prompt_ultra_dense.md")),
        )
        source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    elif artifact.stages["overview"].status == "done":
        print("   [6/6] Abstract skipped (already complete)")

    print("   [render] Writing HTML...")
    artifact = render_outputs(artifact, workspace_dir)
    source_md_path, book_yaml_path = save_artifact(artifact, source_text, workspace_dir)
    return workspace_dir, source_md_path, book_yaml_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a V2 per-book workspace scaffold.")
    parser.add_argument(
        "sources",
        nargs="*",
        help="Optional source book paths. Omit to process every supported file in input/.",
    )
    parser.add_argument(
        "--books-dir",
        default=str(DEFAULT_V2_BOOKS_DIR),
        help="Directory where V2 book workspaces should be created.",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=0,
        help="Optional smoke-test cap on how many blocks to process through the mapper.",
    )
    args = parser.parse_args(argv)

    books_dir = Path(args.books_dir).resolve()
    repo_config = load_repo_config()
    llm_config = repo_config.get("llm", {})
    v2_config = load_v2_config()
    blocking = v2_config.get("blocking", {})
    defaults = v2_config.get("defaults", {})
    profiles = v2_config.get("profiles", {})
    execution = v2_config.get("execution", {})

    base_model = str(llm_config.get("model", "gpt-4o-mini"))
    api_base = llm_config.get("base_url")
    api_key = llm_config.get("api_key")

    default_base_url = defaults.get("base_url", api_base)
    default_api_key = defaults.get("api_key", api_key)
    default_model = defaults.get("model", base_model)
    default_temperature = defaults.get("temperature", llm_config.get("temperature", 0.2))
    default_timeout = int(defaults.get("request_timeout_seconds", 300))
    default_thinking = bool(defaults.get("thinking", True))

    def build_settings(profile_name: str) -> tuple[LLMSettings, dict]:
        profile = resolve_profile(v2_config, profile_name)
        settings = LLMSettings(
            model=str(profile.get("model") or default_model),
            temperature=float(profile.get("temperature") if profile.get("temperature") is not None else default_temperature),
            api_base=profile.get("base_url") or default_base_url,
            api_key=profile.get("api_key") or default_api_key,
            timeout=int(profile.get("request_timeout_seconds") or default_timeout),
            thinking=bool(profile.get("thinking") if profile.get("thinking") is not None else default_thinking),
        )
        return settings, profile

    mini_summary_settings, mini_summary_profile = build_settings("mini_summary")
    cartographer_settings, cartography_profile = build_settings("cartography")
    short_summary_settings, chapter_short_profile = build_settings("chapter_short")
    detailed_summary_settings, chapter_long_profile = build_settings("chapter_long")
    ultra_dense_settings = short_summary_settings
    input_dir = INPUT_DIR.resolve()
    input_dir.mkdir(parents=True, exist_ok=True)
    books_dir.mkdir(parents=True, exist_ok=True)

    source_args = [Path(src).resolve() for src in args.sources]
    if source_args:
        for source_path in source_args:
            if not source_path.exists():
                print(f"❌ Source file not found: {source_path}")
                return 1
        books = source_args
    else:
        books = find_books(input_dir)

    if not books:
        print(f"📂 No books found in {input_dir}/")
        print(f"   Drop .md, .txt, .epub, or .pdf files into {input_dir}/ and run again")
        return 0

    print(f"📚 Found {len(books)} V2 book(s) to process")

    success = 0
    failed = 0
    for source_path in books:
        try:
            workspace_dir, source_md_path, book_yaml_path = prepare_workspace(
                source_path,
                books_dir,
                target_tokens=int(blocking.get("target_tokens", 1024)),
                min_tokens=int(blocking.get("min_tokens", 768)),
                max_tokens=int(blocking.get("max_tokens", 1280)),
                encoding_model=str(blocking.get("encoding_model", "gpt-4o-mini")),
                mini_summary_settings=mini_summary_settings,
                cartographer_settings=cartographer_settings,
                short_summary_settings=short_summary_settings,
                detailed_summary_settings=detailed_summary_settings,
                ultra_dense_settings=ultra_dense_settings,
                mini_summary_profile=mini_summary_profile,
                cartography_profile=cartography_profile,
                chapter_short_profile=chapter_short_profile,
                chapter_long_profile=chapter_long_profile,
                parallel_calls=int(execution.get("parallel_calls", 8)),
                max_blocks=args.max_blocks or None,
            )

            print(f"✅ V2 workspace ready: {workspace_dir}")
            print(f"   source.md: {source_md_path}")
            print(f"   book.yaml: {book_yaml_path}")
            success += 1
        except KeyboardInterrupt:
            print("\n\n⏸️  Interrupted! Progress is saved — run again to resume.")
            return 130
        except Exception as e:
            print(f"\n❌ Error processing {source_path.name}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print(f"\n{'═' * 60}")
    print("🏁 V2 ALL DONE")
    print(f"   ✅ Success: {success}")
    if failed:
        print(f"   ❌ Failed:  {failed}")
    print(f"{'═' * 60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
