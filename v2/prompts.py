# FILE: v2/prompts.py
# PURPOSE: Load simple editable V2 prompt text files from disk.
# OWNS: Prompt path resolution and fallback-free file loading for V2 stages.
# EXPORTS: load_prompt, prompt_path.

from __future__ import annotations

from pathlib import Path

V2_ROOT = Path(__file__).resolve().parent


def prompt_path(filename: str) -> Path:
    return V2_ROOT / filename


def load_prompt(filename: str) -> str:
    path = prompt_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"V2 prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
