---
name: rixie-book-distillation
description: Bootstrap and operate the Rixie book-distillation wrapper from a fresh repo clone. Use when the wrapper has been discovered before setup, when cloning or copying the repo into a new workspace, when customizing `config.yaml` or the prompt templates, when processing `.md`, `.txt`, or `.epub` books, rerunning individual pipeline stages, or debugging output quality.
---

# Rixie Book Distillation

Treat Rixie as a personal template, not a fixed CLI. If you only have this skill, use it to bootstrap a fresh copy of the wrapper repo, customize the config and prompts for the book and reader, then run the pipeline.

## Bootstrap

- Clone or copy the Rixie repo into a working directory.
- Run `uv sync` to install dependencies.
- Use `config.yaml` as the main setup file.
- Keep the three prompt files as the main customization points.

## Customize First

- Edit `config.yaml` before running anything.
- Tune `distill_chunk_prompt.md`, `distill_group_prompt.md`, and `distill_final_prompt.md` to change what gets extracted and how it is phrased.
- Adjust `template.html` and `assets/rixie.jpg` only if you want to change the viewer or branding.
- Treat prompt changes as part of the workflow, not optional polish.

## Run The Pipeline

- Process everything in `input/` with `uv run python process.py`.
- Process one book with `uv run python process.py input/my_book.md`.
- Use `--no-final` or `--no-html` when you want to isolate a stage.
- Rerun a single stage with `chunker.py`, `distiller.py`, `synthesizer.py`, or `export_html.py` when debugging.

## Read The Output

- Start with `final.md` for the big picture.
- Use `synthesis/group_*.md` for the thematic middle layer.
- Use `distilled/*.md` for raw chunk-level detail.
- Open the generated HTML viewer for the full book-specific result.

## Fix Quality Problems

- If extraction is weak or noisy, change the chunk prompt first.
- If topics are duplicated or grouped badly, change the group prompt.
- If the prose reads poorly, change the final prompt.
- Keep book-specific preferences in the prompt files so the wrapper stays reusable.

## EPUB And Audio

- Use `pandoc` for EPUB input.
- Use `audiobook.py` when you want spoken output from `groups.mp3` or `final.mp3`.
- Expect resumable runs; rerun the command after interruption rather than restarting the whole repo from scratch.
