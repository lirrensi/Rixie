# FILE: v2/calibrate.py
# PURPOSE: Fit gate thresholds against stored useful labels, report quality.
# OWNS: CLI `python -m v2.calibrate`, per-book + aggregate sweep, verdict.
# EXPORTS: main, collect_scores, sweep, verdict.
# DOCS: config.yaml, docs/GETTING_STARTED.md
#
# Usage:
#   uv run python -m v2.calibrate                  # all books in output/v2
#   uv run python -m v2.calibrate slug-a slug-b    # subset
#   uv run python -m v2.calibrate --scores out.jsonl --no-run   # re-sweep saved scores
#
# Scores + labels are reused: re-running with the same gate question only
# re-sweeps thresholds (no new model calls) via --scores.

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v2.config import load_v2_config
from v2.decisions import DecisionError, DecisionSettings
from v2.process import DEFAULT_V2_BOOKS_DIR, load_artifact

LOW_GRID = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
HIGH_GRID = [0.60, 0.70, 0.80]


@dataclass
class Row:
    book: str
    block_id: str
    label: bool | None
    score: float | None


def collect_scores(
    books_dir: Path,
    slugs: list[str] | None,
    decision: DecisionSettings,
    batch_blocks: int,
    batch_tokens: int,
    gate_question_file: str,
) -> list[Row]:
    """Score every labeled block via the real pipeline gate path."""
    from v2.cartographer import _gate_useful_scores  # same batching/splitting as prod

    rows: list[Row] = []
    targets = sorted(
        d for d in books_dir.iterdir()
        if d.is_dir() and (d / "book.yaml").exists()
        and (slugs is None or d.name in slugs)
    )
    if not targets:
        raise SystemExit(f"No book.yaml workspaces in {books_dir}")
    t_all = time.time()
    for book_dir in targets:
        artifact = load_artifact(book_dir / "book.yaml")
        source_text = (book_dir / artifact.metadata.source_md).read_text(encoding="utf-8")
        items: list[tuple[str, str]] = []
        labels: dict[str, bool | None] = {}
        for block in artifact.blocks:
            text = block.text
            if not text and block.char_start is not None and block.char_end is not None:
                text = source_text[block.char_start:block.char_end]
            items.append((block.block_id, text or ""))
            labels[block.block_id] = block.useful
        t0 = time.time()
        scores, stats = _gate_useful_scores(
            items,
            decision=decision,
            batch_blocks=batch_blocks,
            batch_tokens=batch_tokens,
            encoding_model="gpt-4o-mini",
            gate_question_file=gate_question_file,
        )
        for block_id, _ in items:
            rows.append(Row(book_dir.name, block_id, labels[block_id], scores.get(block_id)))
        n_err = sum(1 for block_id, _ in items if scores.get(block_id) is None)
        print(
            f"{book_dir.name[:50]:50s} {len(items):>4} blocks "
            f"err={n_err} batches={stats['batches']} splits={stats['splits']} "
            f"{time.time() - t0:.0f}s",
            flush=True,
        )
    print(f"Scored {len(rows)} blocks in {time.time() - t_all:.0f}s", flush=True)
    return rows


def sweep(rows: list[Row]) -> list[dict]:
    """Threshold grid: per (low, high) the skip rate, loss, accuracy-on-acted."""
    usable = [r for r in rows if r.label is not None and r.score is not None]
    n_f = sum(1 for r in usable if r.label is False)
    n_t = sum(1 for r in usable if r.label is True)
    out: list[dict] = []
    for low in LOW_GRID:
        for high in HIGH_GRID:
            if low >= high:
                continue
            skipped = [r for r in usable if r.score <= low]
            acted = [r for r in usable if r.score <= low or r.score >= high]
            tn = sum(1 for r in skipped if r.label is False)
            lost = sum(1 for r in skipped if r.label is True)
            correct = sum(
                1 for r in acted
                if (r.score <= low and r.label is False)
                or (r.score >= high and r.label is True)
            )
            out.append({
                "low": low, "high": high,
                "skipped": len(skipped), "tn": tn, "lost_tp": lost,
                "skip_rate": round(len(skipped) / max(1, len(usable)), 4),
                "recall_noncontent": round(tn / max(1, n_f), 4),
                "acted": len(acted),
                "acc_on_acted": round(correct / max(1, len(acted)), 4),
                "uncertain": len(usable) - len(acted),
                "n": len(usable), "n_f": n_f, "n_t": n_t,
            })
    return out


def verdict(
    table: list[dict],
    *,
    acc_floor: float = 0.90,
    max_loss_rate: float = 0.01,
    loss_cost: float = 10.0,
) -> dict | None:
    """Best passing row under asymmetric cost; None if none passes.

    Passing = acc_on_acted >= acc_floor AND lost-TP rate <= max_loss_rate
    (lost content blocks ÷ all content blocks). Among passing rows, minimize
    ``lost_tp * loss_cost + missed_noncontent`` — losing content costs
    ``loss_cost``× keeping boilerplate; ties break toward higher skip.
    """
    passing = [
        r for r in table
        if r["acc_on_acted"] >= acc_floor and r["lost_tp"] / max(1, r["n_t"]) <= max_loss_rate
    ]
    if not passing:
        return None
    def _cost(r: dict) -> tuple[float, float]:
        missed = r["n_f"] - r["tn"]
        return (r["lost_tp"] * loss_cost + missed, -r["skip_rate"])
    return min(passing, key=_cost)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate the useful/non-content gate against stored labels."
    )
    parser.add_argument("slugs", nargs="*", help="Book workspace slugs (default: all).")
    parser.add_argument("--books-dir", default=str(DEFAULT_V2_BOOKS_DIR))
    parser.add_argument("--scores", default=None,
                        help="Write/read score rows as JSONL (reuse without new model calls).")
    parser.add_argument("--no-run", action="store_true",
                        help="Skip scoring; sweep thresholds from --scores file.")
    parser.add_argument("--acc-floor", type=float, default=0.90,
                        help="Minimum accuracy-on-acted for a passing threshold (default 0.90).")
    parser.add_argument("--max-loss", type=float, default=0.01,
                        help="Maximum lost-content rate (lost TP / all TP, default 0.01).")
    parser.add_argument("--loss-cost", type=float, default=10.0,
                        help="Cost of one lost content block in kept-boilerplate units (default 10).")
    parser.add_argument("--per-book", action="store_true",
                        help="Also print per-book accuracy at the chosen thresholds.")
    args = parser.parse_args(argv)

    t0 = time.time()
    if args.no_run:
        if not args.scores:
            raise SystemExit("--no-run requires --scores")
        rows = [Row(**{k: json.loads(line)[k] for k in ("book", "block_id", "label", "score")}) for line in Path(args.scores).read_text().splitlines()]
        print(f"Loaded {len(rows)} scored rows from {args.scores}", flush=True)
    else:
        v2_config = load_v2_config()
        defaults = v2_config.get("defaults", {})
        execution = v2_config.get("execution", {})
        base = defaults.get("decision_base_url")
        if not base:
            raise SystemExit("No v2.defaults.decision_base_url configured; cannot score.")
        decision = DecisionSettings(
            base_url=str(base),
            model=defaults.get("decision_model"),
            timeout=int(defaults.get("decision_timeout_seconds", 120)),
            enabled=True,
        )
        rows = collect_scores(
            Path(args.books_dir),
            args.slugs or None,
            decision,
            batch_blocks=int(execution.get("decision_batch_blocks", 20)),
            batch_tokens=int(execution.get("decision_batch_tokens", 24000)),
            gate_question_file=str(execution.get("gate_question_file", "question_useful.md")),
        )
        if args.scores:
            Path(args.scores).write_text(
                "\n".join(json.dumps(r.__dict__) for r in rows) + "\n", encoding="utf-8"
            )
            print(f"Wrote {len(rows)} rows to {args.scores}", flush=True)

    usable = [r for r in rows if r.label is not None and r.score is not None]
    n_err = sum(1 for r in rows if r.label is not None and r.score is None)
    n_f = sum(1 for r in usable if r.label is False)
    print(
        f"\nUsable: {len(usable)} labeled+scored "
        f"(T={len(usable) - n_f}, F={n_f}, gate-errors={n_err})", flush=True
    )
    if not usable:
        raise SystemExit("Nothing to calibrate.")

    table = sweep(rows)
    print(f"\n{'low':>5} {'high':>5} {'skip%':>6} {'tn/F':>8} {'lostTP':>7} "
          f"{'accAct':>7} {'acted':>6} {'unc':>6}")
    for r in table:
        flag = " ✓" if r["acc_on_acted"] >= args.acc_floor else ""
        print(
            f"{r['low']:>5.2f} {r['high']:>5.2f} {r['skip_rate']:>6.1%} "
            f"{r['tn']:>4}/{r['n_f']:<4} {r['lost_tp']:>7} "
            f"{r['acc_on_acted']:>7.1%} {r['acted']:>6} {r['uncertain']:>6}{flag}"
        )
    best = verdict(table, acc_floor=args.acc_floor, max_loss_rate=args.max_loss,
                   loss_cost=args.loss_cost)
    print()
    if best is None:
        print(
            f"❌ VERDICT: no threshold reaches {args.acc_floor:.0%} accuracy-on-acted "
            f"with lost-content ≤ {args.max_loss:.1%}. "
            f"Do not enable the gate — reword {load_v2_config().get('execution', {}).get('gate_question_file', 'question_useful.md')} "
            f"and re-run.",
            flush=True,
        )
        return 2
    print(
        f"✅ VERDICT: low={best['low']} high={best['high']} → "
        f"acc-on-acted {best['acc_on_acted']:.1%} (≥ {args.acc_floor:.0%}), "
        f"skip {best['skip_rate']:.1%} of blocks, "
        f"recall on non-content {best['recall_noncontent']:.1%} "
        f"({best['tn']}/{best['n_f']}), "
        f"lost TP {best['lost_tp']}/{best['n_t']} "
        f"({best['lost_tp'] / max(1, best['n_t']):.2%}).",
        flush=True,
    )
    print(
        f"   Set v2.execution: decision_useful_low: {best['low']}  "
        f"decision_useful_high: {best['high']}",
        flush=True,
    )
    if args.per_book:
        print(f"\nPer-book at low={best['low']} high={best['high']}:")
        books = sorted({r.book for r in usable})
        for book in books:
            sub = [r for r in usable if r.book == book]
            acted = [r for r in sub if r.score <= best["low"] or r.score >= best["high"]]
            correct = sum(
                1 for r in acted
                if (r.score <= best["low"] and r.label is False)
                or (r.score >= best["high"] and r.label is True)
            )
            skipped = sum(1 for r in sub if r.score <= best["low"])
            print(
                f"  {book[:48]:48s} n={len(sub):>4} "
                f"acc={correct / max(1, len(acted)):>6.1%} ({correct}/{len(acted)}) "
                f"skipped={skipped}",
                flush=True,
            )
    print(f"\nDone in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
