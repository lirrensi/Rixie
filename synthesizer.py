"""
BookConvert - Synthesizer
Takes distilled lists → concatenates → splits → summarizes → final output.

Flow:
  Step 2: distilled/*.md  →  combined.md          (mechanical concat)
  Step 3: combined.md     →  split chunks         (token-based, newline-aware)
          each chunk      →  LLM with final_prompt
          results         →  final.md              (concat summaries)
"""

import re
import math
import time
from pathlib import Path
from openai import OpenAI

try:
    import tiktoken

    _encoder = tiktoken.encoding_for_model("gpt-4o-mini")
except ImportError:
    _encoder = None


def load_config(config_path: Path = Path("config.yaml")) -> dict:
    if config_path.exists():
        import yaml

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def load_prompt(prompt_path: Path) -> str:
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt file not found: {prompt_path}")


def count_tokens(text: str) -> int:
    """Count tokens precisely (tiktoken) or estimate (chars/4)."""
    if _encoder:
        return len(_encoder.encode(text))
    return len(text) // 4


def load_distilled(distilled_dir: Path) -> list[dict]:
    """Load all distilled chunk files, sorted by index."""
    chunks = []
    for f in sorted(distilled_dir.glob("*_distilled.md")):
        m = re.match(r"^(\d+)_", f.name)
        if m:
            idx = int(m.group(1))
            text = f.read_text(encoding="utf-8")
            body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL).strip()
            title = re.search(r"title:\s*(.+)", text)
            chunks.append(
                {
                    "idx": idx,
                    "title": title.group(1).strip() if title else f.stem,
                    "text": body,
                    "tokens": count_tokens(body),
                }
            )
    return chunks


def concat_distilled(chunks: list[dict], output_path: Path) -> str:
    """Concatenate all distilled lists into a single file.

    This is pure mechanical concat — no LLM, no transformation.
    Each chunk's body (already a list from distillation) is appended.
    """
    parts = []
    for c in chunks:
        parts.append(c["text"])

    combined = "\n\n".join(parts)
    output_path.write_text(combined, encoding="utf-8")

    total_tokens = count_tokens(combined)
    print(f"   📄 Combined {len(chunks)} distilled lists → {output_path.name}")
    print(f"      {total_tokens:,} tokens, {len(combined):,} chars")
    return combined


def split_by_tokens(
    text: str, max_tokens: int, prompt_tokens: int = 2000, response_reserve: int = 8000
) -> list[str]:
    """Split text into chunks that fit max_tokens, respecting line boundaries.

    Strategy:
      1. Split into lines
      2. Accumulate lines until we hit the token budget
      3. At the boundary, start a new chunk
      4. If a single line exceeds budget, it becomes its own chunk (last resort)
    """
    usable = max_tokens - prompt_tokens - response_reserve
    lines = text.split("\n")
    total_tokens = count_tokens(text)

    if total_tokens <= usable:
        return [text]

    # How many chunks do we need?
    num_chunks = math.ceil(total_tokens / usable)
    target_per_chunk = total_tokens // num_chunks

    chunks = []
    current_lines = []
    current_tokens = 0

    for line in lines:
        line_tokens = count_tokens(line + "\n")

        # If adding this line would exceed budget, start new chunk
        if current_lines and (current_tokens + line_tokens > usable):
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_tokens = line_tokens
        else:
            current_lines.append(line)
            current_tokens += line_tokens

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def run_llm(
    client: OpenAI, text: str, prompt: str, model: str, temperature: float
) -> str:
    r = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    )
    content: str | None = r.choices[0].message.content
    if content is None:
        raise RuntimeError(
            f"Model returned None content (finish_reason: {r.choices[0].finish_reason})"
        )
    return str(content)


def synthesize_book(
    distilled_dir: Path,
    synthesis_dir: Path,
    output_dir: Path,
    config: dict,
    final_prompt: str,
    do_final: bool = False,
) -> dict:
    """
    Step 2: Concatenate all distilled lists into one file.
    Step 3: Split combined file → summarize each chunk → concatenate results.
    """
    llm = config.get("llm", {})
    synth = config.get("synthesis", {})

    base_url = llm.get("base_url", "http://localhost:58080/v1")
    api_key = llm.get("api_key", "local")
    model = llm.get("model", "gpt-4o-mini")
    temperature = synth.get("temperature", llm.get("temperature", 0.4))
    context_window = synth.get("context_window", 64000)
    prompt_overhead = synth.get("prompt_overhead", 2000)
    response_reserve = synth.get("response_reserve", 8000)

    client = OpenAI(base_url=base_url, api_key=api_key)
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── Step 2: Concatenate distilled lists ──────────────────
    chunks = load_distilled(distilled_dir)
    print(f"   📚 {len(chunks)} distilled chunks")

    if not chunks:
        return {"chunks": 0, "combined": False, "final": False}

    combined_path = synthesis_dir / "combined.md"

    if combined_path.exists():
        combined = combined_path.read_text(encoding="utf-8")
        print(
            f"   📄 Combined already exists → {combined_path.name} "
            f"({count_tokens(combined):,} tokens, skipped)"
        )
    else:
        combined = concat_distilled(chunks, combined_path)

    # ─── Step 3: Split + Summarize ────────────────────────────
    final_done = False
    final_path = output_dir / "final.md"

    if not do_final:
        return {"chunks": len(chunks), "combined": True, "final": False}

    if final_path.exists():
        print(f"\n   🔄 Final already exists → {final_path.name} (skipped)")
        return {"chunks": len(chunks), "combined": True, "final": True}

    print(f"\n   🔄 Final synthesis...")

    combined_tokens = count_tokens(combined)
    usable = context_window - prompt_overhead - response_reserve
    print(f"      Combined: {combined_tokens:,} tokens | Usable per pass: {usable:,}")

    if combined_tokens <= usable:
        # Fits in one pass — just send it
        print(f"      Fits in one pass ✨")
        try:
            t = time.time()
            result = run_llm(client, combined, final_prompt, model, temperature)
            elapsed = time.time() - t
            print(f"      ✅ {elapsed:.0f}s | {len(result.split(chr(10)))} lines")
        except Exception as e:
            print(f"      ❌ {e}")
            return {"chunks": len(chunks), "combined": True, "final": False}
    else:
        # Split into N chunks, summarize each, concatenate
        parts = split_by_tokens(
            combined, context_window, prompt_overhead, response_reserve
        )
        num_parts = len(parts)
        print(f"      Split into {num_parts} passes")

        summaries = []
        for i, part in enumerate(parts, 1):
            part_tokens = count_tokens(part)
            print(
                f"      [{i}/{num_parts}] {part_tokens:,} tokens...",
                end="",
                flush=True,
            )
            try:
                t = time.time()
                summary = run_llm(client, part, final_prompt, model, temperature)
                elapsed = time.time() - t
                summaries.append(summary)
                print(f" ✅ {elapsed:.0f}s")
            except Exception as e:
                print(f" ❌ {e}")

        if not summaries:
            print(f"      ❌ All passes failed")
            return {"chunks": len(chunks), "combined": True, "final": False}

        result = "\n\n".join(summaries)
        print(
            f"      📦 {num_parts} summaries concatenated → {count_tokens(result):,} tokens"
        )

    # Write final output
    book_name = output_dir.name.replace("_", " ")
    final_output = f"# {book_name}\n\n{result}"
    final_path.write_text(final_output, encoding="utf-8")
    final_done = True
    print(f"      💾 Saved → {final_path.name}")

    return {
        "chunks": len(chunks),
        "combined": True,
        "final": final_done,
    }


if __name__ == "__main__":
    import sys

    config = load_config()
    final_prompt = load_prompt(Path("distill_final_prompt.md"))

    do_final = "--final" in sys.argv

    if len(sys.argv) < 2:
        print(
            "Usage: python synthesizer.py <distilled_dir> [synthesis_dir] [output_dir] [--final]"
        )
        sys.exit(1)

    distilled_dir = Path(sys.argv[1])
    book_dir = distilled_dir.parent
    synthesis_dir = (
        Path(sys.argv[2])
        if len(sys.argv) > 2 and not sys.argv[2].startswith("--")
        else book_dir / "synthesis"
    )
    output_dir = (
        Path(sys.argv[3])
        if len(sys.argv) > 3 and not sys.argv[3].startswith("--")
        else book_dir
    )

    synthesize_book(
        distilled_dir,
        synthesis_dir,
        output_dir,
        config,
        final_prompt,
        do_final,
    )
