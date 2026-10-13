# FILE: v2/prompts.py
# PURPOSE: Load simple editable V2 prompt text files from disk.
# OWNS: Prompt path resolution and fallback-free file loading for V2 stages.
# EXPORTS: load_prompt, prompt_path, load_gate_question.

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


def load_gate_question(filename: str) -> tuple[str, str, str]:
    """Load a decision-gate question file: instructions, true-criteria, false-criteria.

    Format is three sections separated by a line containing only ``---``.
    A leading ``#`` title line in the instructions section is ignored.
    """
    text = load_prompt(filename)
    parts = [p.strip() for p in text.split("\n---\n")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Gate question file must have 3 non-empty `---`-separated sections: {filename}"
        )
    instructions = "\n".join(
        line for line in parts[0].splitlines() if not line.lstrip().startswith("#")
    ).strip()
    if not instructions:
        raise ValueError(f"Gate question has no instructions: {filename}")
    return instructions, parts[1], parts[2]
