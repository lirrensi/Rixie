"""
BookConvert - Book Distiller
Processes each chunk through the intellectual distillation prompt via local LLM.
Resumable: skips already-processed chunks.
"""

import re
import time
from pathlib import Path
from typing import Optional
from openai import OpenAI


def load_config(config_path: Path = Path("config.yaml")) -> dict:
    """Load configuration from YAML file."""
    if config_path.exists():
        import yaml

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "llm": {
            "base_url": "http://localhost:58080/v1",
            "api_key": "local",
            "model": "gpt-4o-mini",
            "temperature": 0.3,
        }
    }


def load_prompt(prompt_path: Path = Path("distill_chunk_prompt.md")) -> str:
    """Load distillation prompt from file."""
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt file not found: {prompt_path}")


def get_processed_chunks(output_dir: Path) -> set:
    """Get set of already processed chunk indices (successful only)."""
    processed = set()
    if output_dir.exists():
        for f in output_dir.glob("*.md"):
            m = re.match(r"^(\d+)_distilled\.md$", f.name)
            if m:
                processed.add(int(m.group(1)))
    return processed


def distill_chunk(
    client: OpenAI,
    chunk_text: str,
    chunk_title: str,
    prompt: str,
    model: str,
    temperature: float,
) -> str:
    """Send a chunk through the distillation prompt."""
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"## Text to Distill: {chunk_title}\n\n{chunk_text}",
            },
        ],
    )
    content = response.choices[0].message.content

    # Check for None (model returned nothing)
    if content is None:
        finish_reason = response.choices[0].finish_reason
        raise RuntimeError(
            f"Model returned None content (finish_reason: {finish_reason})"
        )

    return content


def validate_distillation(
    text: str, min_lines: int = 5, min_chars: int = 200
) -> Optional[str]:
    """Validate that a distillation response is actually useful.

    Returns None if valid, or an error description if not.
    """
    if not text or not text.strip():
        return "Empty response from model"

    stripped = text.strip()
    lines = [l for l in stripped.split("\n") if l.strip()]

    if len(lines) < min_lines:
        return f"Only {len(lines)} non-empty lines (minimum: {min_lines})"

    if len(stripped) < min_chars:
        return f"Only {len(stripped)} characters (minimum: {min_chars})"

    # Check for common error patterns the model might return
    error_patterns = [
        r"^I (can'?t|cannot|am unable)",
        r"^Sorry,? I",
        r"^Error:",
        r"^Unable to",
        r"^I apologize",
        r"^The (text|content) (provided|given) (is|does)",
    ]
    first_line = lines[0].strip()
    for pattern in error_patterns:
        if re.match(pattern, first_line, re.IGNORECASE):
            return f"Model returned error-like response: '{first_line[:80]}'"

    return None


def distill_book(chunks_dir: Path, output_dir: Path, config: dict, prompt: str) -> int:
    """Distill all chunks in a directory. Returns count of newly processed chunks."""
    llm = config.get("llm", {})
    base_url = llm.get("base_url", "http://localhost:58080/v1")
    api_key = llm.get("api_key", "local")
    model = llm.get("model", "gpt-4o-mini")
    temperature = llm.get("temperature", 0.3)

    client = OpenAI(base_url=base_url, api_key=api_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    processed = get_processed_chunks(output_dir)
    chunk_files = sorted(chunks_dir.glob("*.md"))
    chunk_files = [f for f in chunk_files if f.name != "MANIFEST.md"]

    print(f"   📚 Found {len(chunk_files)} chunks | ✅ Already done: {len(processed)}")

    to_process = []
    for f in chunk_files:
        m = re.match(r"^(\d+)_", f.name)
        if m:
            idx = int(m.group(1))
            if idx not in processed:
                to_process.append(f)

    if not to_process:
        print("   🎉 All chunks already distilled!")
        return 0

    print(f"   🔄 To process: {len(to_process)} chunks\n")

    total = len(to_process)
    newly_done = 0
    errors = 0
    for i, chunk_file in enumerate(to_process, 1):
        m = re.match(r"^(\d+)_", chunk_file.name)
        if not m:
            continue
        idx = int(m.group(1))

        chunk_text = chunk_file.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", chunk_text, re.MULTILINE)
        title = title_match.group(1) if title_match else chunk_file.stem

        print(f"   [{i}/{total}] {title[:50]}...", end="", flush=True)

        # Clean up any previous ERROR file for this chunk (we're retrying)
        error_file = output_dir / f"{idx:03d}_ERROR.md"
        if error_file.exists():
            error_file.unlink()

        try:
            start = time.time()
            distilled = distill_chunk(
                client, chunk_text, title, prompt, model, temperature
            )

            # Validate the response — reject empty/useless garbage
            validation_error = validate_distillation(distilled)
            if validation_error:
                elapsed = time.time() - start
                print(f" ❌ {elapsed:.0f}s | {validation_error}")
                error_file.write_text(
                    f"# Validation Failed\n\n{validation_error}\n\n"
                    f"## Raw Response\n\n```\n{distilled[:500]}\n```",
                    encoding="utf-8",
                )
                errors += 1
                continue

            elapsed = time.time() - start

            output_file = output_dir / f"{idx:03d}_distilled.md"
            output_file.write_text(
                f"---\nsource: {chunk_file.name}\ntitle: {title}\nmodel: {model}\n---\n\n{distilled}",
                encoding="utf-8",
            )
            newly_done += 1
            lines = len(distilled.split("\n"))
            print(f" ✅ {elapsed:.0f}s | {lines} lines")

        except Exception as e:
            elapsed = time.time() - start
            print(f" ❌ {elapsed:.0f}s | {e}")
            error_file.write_text(
                f"# Error\n\n{type(e).__name__}: {e}", encoding="utf-8"
            )
            errors += 1

        if i < total:
            time.sleep(0.5)

    if errors:
        print(f"\n   ⚠️  {errors} chunks failed — rerun to retry")
    print(f"\n   ✨ Distilled {newly_done} new chunks → {output_dir.name}/")
    return newly_done


if __name__ == "__main__":
    import sys

    config = load_config()
    prompt = load_prompt()

    if len(sys.argv) < 2:
        print("Usage: python distiller.py <chunks_dir> [output_dir]")
        sys.exit(1)

    chunks_dir = Path(sys.argv[1])
    output_dir = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else chunks_dir.parent / "distilled"
    )
    distill_book(chunks_dir, output_dir, config, prompt)
