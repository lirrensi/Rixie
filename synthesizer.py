"""
BookConvert - Synthesizer
Groups distillations → Final merge.

Flow:
  distilled/*.md  →  synthesis/group_N.md  →  output/final.md

Max context window controls how many chunks per group.
Final merge is optional (--final flag).
"""

import re
import math
import time
from pathlib import Path
from openai import OpenAI


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


def est_tokens(text: str) -> int:
    return len(text) // 4


def load_distilled(distilled_dir: Path) -> list[dict]:
    """Load all distilled chunk files."""
    chunks = []
    for f in sorted(distilled_dir.glob("*_distilled.md")):
        m = re.match(r"^(\d+)_", f.name)
        if m:
            idx = int(m.group(1))
            text = f.read_text(encoding="utf-8")
            body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)
            title = re.search(r"title:\s*(.+)", text)
            chunks.append(
                {
                    "idx": idx,
                    "title": title.group(1).strip() if title else f.stem,
                    "text": body,
                    "tokens": est_tokens(body),
                }
            )
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
    return r.choices[0].message.content


def synthesize_book(
    distilled_dir: Path,
    synthesis_dir: Path,
    output_dir: Path,
    config: dict,
    group_prompt: str,
    final_prompt: str,
    do_final: bool = False,
) -> dict:
    """
    Run group synthesis + optional final merge.
    Returns dict with stats.
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
    usable = context_window - prompt_overhead - response_reserve

    client = OpenAI(base_url=base_url, api_key=api_key)
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = load_distilled(distilled_dir)
    print(f"   📚 {len(chunks)} distilled chunks")

    if not chunks:
        return {"chunks": 0, "groups": 0, "final": False}

    # Auto-calculate group size
    avg = sum(c["tokens"] for c in chunks) / len(chunks)
    group_size = max(1, int(usable / avg))
    num_groups = math.ceil(len(chunks) / group_size)

    print(f"   Avg: {avg:.0f} tokens | Context: {context_window:,}")
    print(f"   → {group_size} chunks/group → {num_groups} groups\n")

    # ─── Group distillation ──────────────────────────────────
    group_files = []
    existing_groups = sorted(synthesis_dir.glob("group_*.md"))
    existing_group_count = len(existing_groups)

    for g in range(num_groups):
        group_num = g + 1
        group_file = synthesis_dir / f"group_{group_num:02d}.md"

        # Check if already exists (resumability)
        if group_file.exists():
            print(
                f"   [{group_num}/{num_groups}] Already exists → {group_file.name} (skipped)"
            )
            group_files.append(group_file)
            continue

        start = g * group_size
        end = min(start + group_size, len(chunks))
        group = chunks[start:end]

        titles = [c["title"] for c in group]
        tok = sum(c["tokens"] for c in group)
        print(f"   [{group_num}/{num_groups}] {titles[0][:30]} ... {titles[-1][:30]}")
        print(f"              {len(group)} chunks, ~{tok:,} tokens")

        combined = "\n\n".join(f"### {c['title']}\n{c['text']}" for c in group)

        try:
            t = time.time()
            result = run_llm(client, combined, group_prompt, model, temperature)
            elapsed = time.time() - t

            group_file.write_text(result, encoding="utf-8")
            group_files.append(group_file)

            lines = len(result.split("\n"))
            print(
                f"              ✅ {elapsed:.0f}s | {lines} lines → {group_file.name}"
            )
        except Exception as e:
            print(f"              ❌ {e}")

    print(f"\n   📄 {len(group_files)} group distillations in {synthesis_dir.name}/")

    # ─── Final merge (optional) ──────────────────────────────
    final_done = False
    final_path = output_dir / "final.md"

    if do_final:
        # Check if final already exists
        if final_path.exists():
            print(f"\n   🔄 Final merge already exists → {final_path.name} (skipped)")
            final_done = True
        # If only 1 group, skip rephrasing — just use it as-is
        elif len(group_files) == 1:
            print(f"\n   🔄 Single group → using directly (no re-synthesis)")
            content = group_files[0].read_text(encoding="utf-8")
            final_path.write_text(content, encoding="utf-8")
            final_done = True
            print(f"      ✅ Copied → {final_path.name}")
        else:
            print(f"\n   🔄 Final merge...")

            combined = "\n\n---\n\n".join(
                f"## Group {i + 1}\n{f.read_text(encoding='utf-8')}"
                for i, f in enumerate(group_files)
            )

            combined_tok = est_tokens(combined)
            print(f"      Combined: ~{combined_tok:,} tokens (limit: {usable:,})")

            if combined_tok > usable:
                print(f"      ⚠️  Too large! Increase context_window in config.yaml.")
            else:
                try:
                    t = time.time()
                    result = run_llm(client, combined, final_prompt, model, temperature)
                    elapsed = time.time() - t

                    final_path.write_text(result, encoding="utf-8")
                    final_done = True
                    print(
                        f"      ✅ {elapsed:.0f}s | {len(result.split(chr(10)))} lines → {final_path.name}"
                    )
                except Exception as e:
                    print(f"      ❌ {e}")

    return {
        "chunks": len(chunks),
        "groups": len(group_files),
        "final": final_done,
    }


if __name__ == "__main__":
    import sys

    config = load_config()
    group_prompt = load_prompt(Path("distill_group_prompt.md"))
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
        group_prompt,
        final_prompt,
        do_final,
    )
