# FILE: v1/synthesizer.py
# PURPOSE: Merge legacy distilled chunks into combined and optional final synthesized outputs.
# OWNS: V1 combined artifact creation, token-aware splitting, and final synthesis requests.
# EXPORTS: count_tokens, load_config, load_prompt, main, synthesize_book.
# DOCS: README.md, v1/process.py

"""
BookConvert - Synthesizer
Takes distilled lists → concatenates → splits → summarizes → final output.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path

import yaml
from openai import OpenAI

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v1._paths import resolve_asset_path, resolve_config_path

try:
    import tiktoken

    _encoder = tiktoken.encoding_for_model("gpt-4o-mini")
except ImportError:
    _encoder = None


def load_config(config_path: Path | None = None) -> dict:
    config_path = config_path or resolve_config_path()
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_prompt(prompt_path: Path | None = None) -> str:
    prompt_path = prompt_path or resolve_asset_path("distill_final_prompt.md")
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt file not found: {prompt_path}")


def count_tokens(text: str) -> int:
    if _encoder:
        return len(_encoder.encode(text))
    return len(text) // 4


def load_distilled(distilled_dir: Path) -> list[dict]:
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
    parts = [c["text"] for c in chunks]
    combined = "\n\n".join(parts)
    output_path.write_text(combined, encoding="utf-8")

    total_tokens = count_tokens(combined)
    print(f"   📄 Combined {len(chunks)} distilled lists → {output_path.name}")
    print(f"      {total_tokens:,} tokens, {len(combined):,} chars")
    return combined


def split_evenly(text: str, target_tokens: int) -> list[str]:
    total_tokens = count_tokens(text)
    if total_tokens <= target_tokens:
        return [text]

    num_chunks = math.ceil(total_tokens / target_tokens)
    tokens_per_chunk = total_tokens // num_chunks
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)
        if current_chunk and (current_tokens + para_tokens > tokens_per_chunk):
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [para]
            current_tokens = para_tokens
        else:
            current_chunk.append(para)
            current_tokens += para_tokens

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def run_llm(
    client: OpenAI,
    text: str,
    prompt: str,
    model: str,
    temperature: float,
    timeout: int | None = None,
) -> str:
    kwargs = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    }
    if timeout:
        kwargs["timeout"] = timeout
    r = client.chat.completions.create(**kwargs)
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
    llm = config.get("llm", {})
    synth = config.get("synthesis", {})

    base_url = llm.get("base_url", "http://localhost:58080/v1")
    api_key = llm.get("api_key", "local")
    model = llm.get("model", "gpt-4o-mini")
    temperature = synth.get("temperature", llm.get("temperature", 0.4))
    timeout = int(llm.get("request_timeout_seconds", 300))
    context_window = synth.get("context_window", 64000)
    prompt_overhead = synth.get("prompt_overhead", 2000)
    response_reserve = synth.get("response_reserve", 8000)
    final_chunk_size = synth.get("final_chunk_size", 0)

    client = OpenAI(base_url=base_url, api_key=api_key)
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = load_distilled(distilled_dir)
    print(f"   📚 {len(chunks)} distilled chunks")
    if not chunks:
        return {"chunks": 0, "combined": False, "final": False}

    combined_path = synthesis_dir / "combined.md"
    if combined_path.exists():
        combined = combined_path.read_text(encoding="utf-8")
        print(
            f"   📄 Combined already exists → {combined_path.name} ({count_tokens(combined):,} tokens, skipped)"
        )
    else:
        combined = concat_distilled(chunks, combined_path)

    final_path = output_dir / "final.md"
    if not do_final:
        return {"chunks": len(chunks), "combined": True, "final": False}
    if final_path.exists():
        print(f"\n   🔄 Final already exists → {final_path.name} (skipped)")
        return {"chunks": len(chunks), "combined": True, "final": True}

    print("\n   🔄 Final synthesis...")
    usable = context_window - prompt_overhead - response_reserve
    target_chunk = final_chunk_size - prompt_overhead - response_reserve if final_chunk_size > 0 else usable
    combined_tokens = count_tokens(combined)
    print(f"      Combined: {combined_tokens:,} tokens | Target: {target_chunk:,}")

    if combined_tokens <= target_chunk:
        print("      Fits in one pass ✨")
        try:
            t = time.time()
            result = run_llm(client, combined, final_prompt, model, temperature, timeout)
            elapsed = time.time() - t
            print(f"      ✅ {elapsed:.0f}s | {len(result.split(chr(10)))} lines")
        except Exception as e:
            print(f"      ❌ {e}")
            return {"chunks": len(chunks), "combined": True, "final": False}
    else:
        parts = split_evenly(combined, target_chunk)
        num_parts = len(parts)
        print(
            f"      Split into {num_parts} equal passes (~{combined_tokens // num_parts:,} tokens each)"
        )
        summaries = []
        for i, part in enumerate(parts, 1):
            part_tokens = count_tokens(part)
            print(f"      [{i}/{num_parts}] {part_tokens:,} tokens...", end="", flush=True)
            try:
                t = time.time()
                summary = run_llm(client, part, final_prompt, model, temperature, timeout)
                elapsed = time.time() - t
                summaries.append(summary)
                print(f" ✅ {elapsed:.0f}s")
            except Exception as e:
                print(f" ❌ {e}")

        if not summaries:
            print("      ❌ All passes failed")
            return {"chunks": len(chunks), "combined": True, "final": False}
        result = "\n\n".join(summaries)
        print(
            f"      📦 {num_parts} summaries concatenated → {count_tokens(result):,} tokens"
        )

    book_name = output_dir.name.replace("_", " ")
    final_output = f"# {book_name}\n\n{result}"
    final_path.write_text(final_output, encoding="utf-8")
    print(f"      💾 Saved → {final_path.name}")
    return {"chunks": len(chunks), "combined": True, "final": True}


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if not argv:
        import sys

        argv = sys.argv[1:]

    config = load_config()
    final_prompt = load_prompt()
    do_final = "--final" in argv
    args = [arg for arg in argv if not arg.startswith("--")]

    if len(args) < 1:
        print(
            "Usage: python synthesizer.py <distilled_dir> [synthesis_dir] [output_dir] [--final]"
        )
        return 1

    distilled_dir = Path(args[0])
    book_dir = distilled_dir.parent
    synthesis_dir = Path(args[1]) if len(args) > 1 else book_dir / "synthesis"
    output_dir = Path(args[2]) if len(args) > 2 else book_dir
    synthesize_book(
        distilled_dir,
        synthesis_dir,
        output_dir,
        config,
        final_prompt,
        do_final,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
